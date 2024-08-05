import fcntl
import getpass
import glob
import json
import os
import pty
import pyperclip
import readline
import requests
import select
import signal
import struct
import subprocess
import sys
import termios
import tty

from typing import List, Tuple

def format_text(fg, bg=None, inverted=False, bold=False):
    reset = "\033[0m"
    result = reset
    if bold:
        result += "\033[1m"
    if inverted:
        result += "\033[7m"
    fg_codes = {'black': '30', 'red': '31', 'green': '32', 'yellow': '33', 
                'blue': '34', 'magenta': '35', 'cyan': '36', 'white': '37'}
    bg_codes = {'black': '40', 'red': '41', 'green': '42', 'yellow': '43', 
                'blue': '44', 'magenta': '45', 'cyan': '46', 'white': '47'}
    result += f'\033[{fg_codes.get(fg, "37")}m'
    if bg:
        result += f'\033[{bg_codes.get(bg, "40")}m'
    return result

def reset_format():
    return "\033[0m"

class Node:
    def __init__(self, model_name: str, name: str, max_tokens: int = 8192):
        self.model_name = model_name
        self.name = name
        self.definition = ""
        self.context = []
        self.max_tokens = max_tokens

    def __call__(self, input_text: str, additional_data: dict = None):
        try:
            context_str = "\n".join([f"<|start_header_id|>{msg['role']}<|end_header_id|> {msg['content']}<|eot_id|>" for msg in self.context])
            
            prompt = f"""<|start_header_id|>system<|end_header_id|>{self.definition}<|eot_id|>
{context_str}
<|start_header_id|>user<|end_header_id|>{input_text}<|eot_id|>"""

            if additional_data:
                prompt += "\n<|start_header_id|>system<|end_header_id|>Additional data:\n"
                for key, value in additional_data.items():
                    prompt += f"{key}: {value}\n"
                prompt += "<|eot_id|>"

            prompt += "\n<|start_header_id|>assistant<|end_header_id|>"

            response = requests.post('http://localhost:11434/api/generate', 
                                     json={
                                         "model": self.model_name,
                                         "prompt": prompt,
                                         "stream": False,
                                         "options": {
                                             "stop": ["<|start_header_id|>", "<|end_header_id|>", "<|eot_id|>"],
                                             "num_predict": self.max_tokens
                                         }
                                     })
            
            if response.status_code == 200:
                output = response.json()['response'].strip()
                self.context.append({"role": "user", "content": input_text})
                self.context.append({"role": "assistant", "content": output})
                return output
            else:
                return f"Error in Ollama API call: {response.status_code} - {response.text}"
        except Exception as e:
            return f"Error in processing: {str(e)}"

class DataGatherer:
    @staticmethod
    def get_clipboard_content():
        try:
            return pyperclip.paste()
        except:
            return "Error: Unable to access clipboard"

    @staticmethod
    def get_file_content(file_path):
        try:
            with open(file_path, 'r') as file:
                return file.read()
        except Exception as e:
            return f"Error reading file: {str(e)}"

    @staticmethod
    def execute_command(command):
        try:
            result = subprocess.run(command, capture_output=True, text=True, shell=True)
            return result.stdout if result.returncode == 0 else f"Error: {result.stderr}"
        except Exception as e:
            return f"Error executing command: {str(e)}"

class AITerminalAssistant:
    def __init__(self, model_name: str = "llama3.1:8b", max_tokens: int = 16384):
        self.username = getpass.getuser()
        self.home_folder = os.path.expanduser("~")
        self.current_directory = os.getcwd()

        self.command_executor = Node(model_name, "Command Executor", max_tokens=max_tokens)
        self.error_handler = Node(model_name, "Error Handler", max_tokens=max_tokens)
        self.debugger = Node(model_name, "Debugger Expert", max_tokens=max_tokens)
        self.merger = Node(model_name, "Code Merger", max_tokens=max_tokens)
        self.question_answerer = Node(model_name, "Question Answerer", max_tokens=max_tokens)
        self.data_gatherer = DataGatherer()

        self.command_history = []
        self.initialize_system_context()

    def initialize_system_context(self):
        path_dirs = os.environ.get('PATH', '').split(os.pathsep)
        installed_commands = []
        for dir in path_dirs:
            if os.path.isdir(dir):
                installed_commands.extend([f for f in os.listdir(dir) if os.access(os.path.join(dir, f), os.X_OK)])
        installed_commands = list(set(installed_commands))
        
        try:
            system_info = subprocess.check_output("uname -a", shell=True, text=True).strip()
        except subprocess.CalledProcessError:
            system_info = "Unable to retrieve system information"
        
        desktop_env = os.environ.get('XDG_CURRENT_DESKTOP', 'Unknown')
        
        accessibility_tools = self.get_accessibility_tools()

        self.command_executor.definition = f"""
        Interpret and convert user input into a SINGLE shell command. Return ONLY the command, nothing else.
        Use these details for context:
        - Username: {self.username}
        - Home folder: {self.home_folder}
        - Current working directory: {self.current_directory}
        - System information: {system_info}
        - Desktop environment: {desktop_env}
        - Installed commands: {', '.join(installed_commands[:100])}
        - Available accessibility tools: {', '.join(accessibility_tools)}
        IMPORTANT:
        - If the input is already a valid shell command, return it as is.
        - For natural language queries, translate to the most appropriate single command.
        - Do NOT use 'cd' or try to navigate directories unless explicitly asked by the user.
        - For file operations, assume the current directory unless specified otherwise.
        - For queries about directory contents, use 'ls' without any path arguments.
        - For file type queries, use 'file' command.
        - For file size queries, use 'du -h' with the filename.
        - For creating multiple files, use a for loop: for i in $(seq 1 10); do touch $i.txt; done
        - DO NOT use brace expansion {{1..10}} as it may not work in all environments.
        - DO NOT combine multiple commands using ';', '&&', or '|'.
        - DO NOT provide any explanations or comments. Return ONLY the command.
        - For accessibility-related queries, use the appropriate tools from the list provided.
        - Always use the actual filenames provided in the additional data, not placeholders.
        - Ensure to properly escape any special characters to maintain shell compatibility.
        """

        self.error_handler.definition = "Analyze errors and provide a single, simple corrected command. Do not provide explanations."

        self.debugger.definition = """
        You are an expert debugger for shell commands and terminal operations.
        Your task is to analyze error messages and command history to provide helpful suggestions.
        Consider common issues like file permissions, typos, missing directories, and incorrect syntax.
        Provide clear, concise explanations and suggest possible solutions or alternative commands.
        """

        self.merger.definition = """
        You are an expert at merging code and applying feedback. Given an existing Python script and feedback or 
        modifications, your task is to create an updated version of the script that incorporates the feedback.
        Follow these guidelines strictly:
        1. Preserve ALL existing code. Do not remove or modify any existing code unless explicitly instructed to do so.
        2. Analyze both the existing code and the feedback carefully.
        3. Only add or modify code that is directly related to the feedback.
        4. If the feedback suggests changes to a specific function, only update that function.
        5. Maintain consistent coding style and follow Python best practices.
        6. If the feedback is unclear or could be interpreted in multiple ways, choose the most conservative interpretation.
        7. Provide the entire updated Python script as your response, including ALL unchanged parts.
        8. Add a comment '# Updated based on feedback' above any function or section you modify or add.
        9. If you're unsure about a change, err on the side of preserving the existing code.
        """

        self.question_answerer.definition = """
        You are an expert at answering questions related to shell commands, file systems, and general computing topics.
        Your task is to provide clear, concise, and accurate answers to user questions.
        Use the context provided, including command history and current directory, to give more relevant answers.
        If a question is ambiguous, ask for clarification.
        Provide examples when appropriate to illustrate your points.
        """

    def get_accessibility_tools(self):
        accessibility_tools = []
        potential_tools = ['orca', 'festival', 'espeak', 'brltty', 'at-spi2-core']
        
        for tool in potential_tools:
            if subprocess.call(['which', tool], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                accessibility_tools.append(tool)
        
        return accessibility_tools

    def execute_command_with_live_output(self, command: str) -> Tuple[str, str, int]:
        interactive_commands = ['top', 'nano', 'vim', 'less', 'more']
        is_interactive = any(command.strip().startswith(cmd) for cmd in interactive_commands)

        if is_interactive:
            return self.execute_interactive_command(command)

        if command.strip().startswith('sudo'):
            command = f"sudo -S {command[5:]}"
        
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            shell=True,
            universal_newlines=True,
            preexec_fn=os.setsid
        )

        for pipe in [process.stdout, process.stderr]:
            flags = fcntl.fcntl(pipe, fcntl.F_GETFL)
            fcntl.fcntl(pipe, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        stdout_data, stderr_data = [], []

        try:
            if command.startswith('sudo -S'):
                password = getpass.getpass("Enter sudo password: ")
                process.stdin.write(f"{password}\n")
                process.stdin.flush()

            while True:
                ready, _, _ = select.select([process.stdout, process.stderr], [], [], 0.1)
                
                if process.stdout in ready:
                    stdout = process.stdout.read()
                    if stdout:
                        print(stdout, end='', flush=True)
                        stdout_data.append(stdout)
                
                if process.stderr in ready:
                    stderr = process.stderr.read()
                    if stderr:
                        print(f"{format_text('red')}{stderr}{reset_format()}", end='', flush=True)
                        stderr_data.append(stderr)
                
                if process.poll() is not None:
                    break

            stdout, stderr = process.communicate(timeout=0.1)
            if stdout:
                print(stdout, end='', flush=True)
                stdout_data.append(stdout)
            if stderr:
                print(f"{format_text('red')}{stderr}{reset_format()}", end='', flush=True)
                stderr_data.append(stderr)

        except KeyboardInterrupt:
            os.killpg(os.getpgid(process.pid), signal.SIGINT)
            print("\nCommand interrupted by user.")
        except Exception as e:
            print(f"{format_text('red')}Error during command execution: {str(e)}{reset_format()}")
        finally:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except:
                pass
        
        exit_code = process.returncode if process.returncode is not None else -1
        full_stdout = ''.join(stdout_data)
        full_stderr = ''.join(stderr_data)

        return full_stdout, full_stderr, exit_code

    def execute_interactive_command(self, command: str) -> Tuple[str, str, int]:
        try:
            pid, fd = pty.fork()

            if pid == 0:  # Child process
                os.execvp(command.split()[0], command.split())
            else:  # Parent process
                old_term = termios.tcgetattr(sys.stdin)
                tty.setraw(sys.stdin.fileno())

                rows, cols = struct.unpack('hh', fcntl.ioctl(sys.stdin, termios.TIOCGWINSZ, b'1234'))

                try:
                    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('hh', rows, cols))

                    while True:
                        try:
                            data = os.read(fd, 1024)
                            if not data:
                                break
                            sys.stdout.write(data.decode())
                            sys.stdout.flush()
                        except OSError:
                            break

                        if select.select([sys.stdin], [], [], 0)[0]:
                            input_data = sys.stdin.read(1)
                            os.write(fd, input_data.encode())

                finally:
                    termios.tcsetattr(sys.stdin, termios.TCSAFLUSH, old_term)

            _, exit_status = os.waitpid(pid, 0)
            exit_code = exit_status >> 8

            return "", "", exit_code

        except Exception as e:
            print(f"{format_text('red')}Error during interactive command execution: {str(e)}{reset_format()}")
            return "", str(e), -1

    def execute_command(self, user_input: str) -> str:
        try:
            self.current_directory = os.getcwd()
            
            if user_input.startswith('?') or user_input.endswith('?'):
                return self.answer_question(user_input)

            if user_input.startswith('!'):
                return self.run_direct_command(user_input[1:])
            
            additional_data = self.gather_additional_data(user_input)

            command = self.command_executor(f"""
            User Input: {user_input}
            Current Directory: {self.current_directory}
            Translate the user input into a SINGLE shell command. Return ONLY the command, nothing else.
            If the input is already a valid shell command, return it as is.
            Do not provide any explanations or comments.
            Use the actual filenames and content provided in the additional data.
            """, additional_data=additional_data).strip()
            
            formatted_command = f"{format_text('white', inverted=True)}Command: {command}{reset_format()}"
            print(formatted_command)

            self.command_history.append(command)
            if len(self.command_history) > 10:
                self.command_history.pop(0)

            if command.startswith("cd "):
                path = command.split(" ", 1)[1]
                os.chdir(os.path.expanduser(path))
                result = f"Changed directory to {os.getcwd()}"
                exit_code = 0
            else:
                stdout, stderr, exit_code = self.execute_command_with_live_output(command)
                result = ""

            if exit_code != 0:
                debug_suggestion = self.debug_error(command, stderr, exit_code)
                result += f"\n\n{format_text('yellow', bold=True)}Debugging Suggestion:{reset_format}\n{debug_suggestion}"

            return result.strip()
        except Exception as e:
            return self.handle_error(str(e), user_input, command)

    def run_direct_command(self, command: str) -> str:
        try:
            formatted_command = f"{format_text('white', inverted=True)}Direct Command: {command}{reset_format()}"
            print(formatted_command)

            self.command_history.append(command)
            if len(self.command_history) > 10:
                self.command_history.pop(0)

            stdout, stderr, exit_code = self.execute_command_with_live_output(command)

            result = ""

            if exit_code != 0:
                debug_suggestion = self.debug_error(command, stderr, exit_code)
                result += f"\n\n{format_text('yellow', bold=True)}Debugging Suggestion:{reset_format}\n{debug_suggestion}"

            return result.strip()
        except Exception as e:
            return self.handle_error(str(e), command, command)

    def answer_question(self, question: str) -> str:
        context = f"""
        Command History (last 10 commands):
        {', '.join(self.command_history)}

        Current Directory: {self.current_directory}
        """

        answer = self.question_answerer(f"""
        Question: {question.strip('?')}

        Context:
        {context}

        Please provide a clear and concise answer to the question, taking into account the given context.
        """)

        return f"{format_text('cyan', bold=True)}Answer:{reset_format}\n{answer}"

    def gather_additional_data(self, user_input: str) -> dict:
        additional_data = {}
        
        if "clipboard" in user_input.lower():
            clipboard_content = self.data_gatherer.get_clipboard_content()
            additional_data["clipboard_content"] = clipboard_content

        file_keywords = ["file", "content", "read", "merge"]
        if any(keyword in user_input.lower() for keyword in file_keywords):
            words = user_input.split()
            for word in words:
                if os.path.isfile(word):
                    with open(word, 'r') as file:
                        file_content = file.read()
                    additional_data["file_content"] = file_content
                    additional_data["target_file"] = word
                    break
        
        return additional_data

    def debug_error(self, command: str, error_output: str, exit_code: int) -> str:
        context = f"""
        Command History (last 10 commands):
        {', '.join(self.command_history)}

        Current Directory: {self.current_directory}
        Last Command: {command}
        Error Output: {error_output}
        Exit Code: {exit_code}
        """

        debug_input = f"""
        Analyze the following command and its error output.
        Provide a brief explanation of what went wrong and suggest a solution or alternative approach.
        Keep your response concise and focused on solving the immediate issue.

        {context}
        """

        return self.debugger(debug_input)

    def handle_error(self, error: str, user_input: str, command: str) -> str:
        error_analysis = self.error_handler(f"""
        Error: {error}
        User Input: {user_input}
        Interpreted Command: {command}
        Current Directory: {self.current_directory}
        Provide ONLY a single, simple corrected command. No explanations.
        """)
        
        error_msg = f"{format_text('red', bold=True)}Error occurred: {error}{reset_format()}"
        suggestion_msg = f"{format_text('yellow', bold=True)}Suggested command: {error_analysis}{reset_format()}"
        
        print(error_msg)
        print(suggestion_msg)
        
        confirmation = input(f"Would you like to execute the suggested command? (y/n) ")
        if confirmation.lower() == 'y':
            return self.execute_command(error_analysis)
        
        return f"{format_text('red', bold=True)}Command execution aborted.{reset_format()}"

def setup_readline():
    readline.parse_and_bind('tab: complete')
    
    def complete(text, state):
        return (glob.glob(os.path.expanduser(text) + '*') + [None])[state]
    
    readline.set_completer(complete)
    readline.set_completer_delims(' \t\n;')

def main():
    assistant = AITerminalAssistant()
    setup_readline()
    
    print(f"{format_text('green', bold=True)}Welcome to the Enhanced AI-Powered Terminal Assistant!")
    print("This assistant interacts with your real file system and can gather additional data. Use with caution.")
    print("You can use natural language queries or standard shell commands.")
    print("Start or end your input with '?' to ask a question.")
    print("Start your input with '!' to execute a command directly without processing.")
    print(f"Type 'exit' to quit.{reset_format()}")

    while True:
        try:
            user_input = input(f"{format_text('green', bold=True)}{os.getcwd()}$ {reset_format()}")
            if user_input.lower() == 'exit':
                break

            result = assistant.execute_command(user_input)
            print(result)

        except KeyboardInterrupt:
            print("\nKeyboardInterrupt")

    print(f"{format_text('green', bold=True)}Goodbye!{reset_format()}")

if __name__ == "__main__":
    main()
