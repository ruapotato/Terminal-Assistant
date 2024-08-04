import os
import subprocess
import shlex
import getpass
from typing import List, Tuple
import readline
import glob
import requests
import json
import sys

# VT100 color and text format functions
def format_text(fg, bg=None, inverted=False, bold=False):
    return_vt = "\033[0m"  # Reset all attributes
    if bold:
        return_vt += "\033[1m"
    if inverted:
        return_vt += "\033[7m"
    fg_codes = {'black': '30', 'red': '31', 'green': '32', 'yellow': '33', 
                'blue': '34', 'magenta': '35', 'cyan': '36', 'white': '37'}
    bg_codes = {'black': '40', 'red': '41', 'green': '42', 'yellow': '43', 
                'blue': '44', 'magenta': '45', 'cyan': '46', 'white': '47'}
    return_vt += f'\033[{fg_codes.get(fg, "37")}m'
    if bg:
        return_vt += f'\033[{bg_codes.get(bg, "40")}m'
    return return_vt

def reset_format():
    return "\033[0m"

def vt_write(vt100):
    sys.stdout.write(vt100)
    sys.stdout.flush()

class Node:
    def __init__(self, model_name: str, name: str, max_tokens: int = 8192):
        self.model_name = model_name
        self.name = name
        self.definition = ""
        self.context = []
        self.max_tokens = max_tokens

    def __call__(self, input_text: str):
        try:
            context_str = "\n".join([f"<|start_header_id|>{msg['role']}<|end_header_id|> {msg['content']}<|eot_id|>" for msg in self.context])
            
            prompt = f"""<|start_header_id|>system<|end_header_id|>{self.definition}<|eot_id|>
{context_str}
<|start_header_id|>user<|end_header_id|>{input_text}<|eot_id|>
<|start_header_id|>assistant<|end_header_id|>"""

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

class AITerminalAssistant:
    def __init__(self, model_name: str = "llama3.1:8b", max_tokens: int = 16384):
        self.username = getpass.getuser()
        self.home_folder = os.path.expanduser("~")
        self.current_directory = os.getcwd()

        self.command_executor = Node(model_name, "Command Executor", max_tokens=max_tokens)
        self.error_handler = Node(model_name, "Error Handler", max_tokens=max_tokens)
        self.debugger = Node(model_name, "Debugger Expert", max_tokens=max_tokens)

        self.command_history = []
        self.initialize_system_context()

    def initialize_system_context(self):
        # Get installed commands
        path_dirs = os.environ.get('PATH', '').split(os.pathsep)
        installed_commands = []
        for dir in path_dirs:
            if os.path.isdir(dir):
                installed_commands.extend([f for f in os.listdir(dir) if os.access(os.path.join(dir, f), os.X_OK)])
        installed_commands = list(set(installed_commands))  # Remove duplicates
        
        # Get system information
        try:
            system_info = subprocess.check_output("uname -a", shell=True, text=True).strip()
        except subprocess.CalledProcessError:
            system_info = "Unable to retrieve system information"
        
        # Get desktop environment (if any)
        desktop_env = os.environ.get('XDG_CURRENT_DESKTOP', 'Unknown')
        
        # Get accessibility tools
        accessibility_tools = self.get_accessibility_tools()

        self.command_executor.definition = f"""
        Interpret and convert user input into a SINGLE shell command. Return ONLY the command, nothing else.
        Use these details for context:
        - Username: {self.username}
        - Home folder: {self.home_folder}
        - Current working directory: {self.current_directory}
        - System information: {system_info}
        - Desktop environment: {desktop_env}
        - Installed commands: {', '.join(installed_commands[:100])}  # Limiting to first 100 for brevity
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
        """

        self.error_handler.definition = "Analyze errors and provide a single, simple corrected command. Do not provide explanations."

        self.debugger.definition = """
        You are an expert debugger for shell commands and terminal operations.
        Your task is to analyze error messages and command history to provide helpful suggestions.
        Consider common issues like file permissions, typos, missing directories, and incorrect syntax.
        Provide clear, concise explanations and suggest possible solutions or alternative commands.
        """

    def get_accessibility_tools(self):
        accessibility_tools = []
        potential_tools = ['orca', 'festival', 'espeak', 'brltty', 'at-spi2-core']
        
        for tool in potential_tools:
            if subprocess.call(['which', tool], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                accessibility_tools.append(tool)
        
        return accessibility_tools

    def execute_command(self, user_input: str) -> str:
        try:
            self.current_directory = os.getcwd()
            
            command = self.command_executor(f"""
            User Input: {user_input}
            Current Directory: {self.current_directory}
            Translate the user input into a SINGLE shell command. Return ONLY the command, nothing else.
            If the input is already a valid shell command, return it as is.
            Do not provide any explanations or comments.
            """).strip()
            
            # Format the command (inverted)
            formatted_command = f"{format_text('white', inverted=True)}Command: {command}{reset_format()}"
            print(formatted_command)

            # Add command to history
            self.command_history.append(command)
            if len(self.command_history) > 10:  # Keep only last 10 commands
                self.command_history.pop(0)

            if command.startswith("cd "):
                path = command.split(" ", 1)[1]
                os.chdir(os.path.expanduser(path))
                result = f"Changed directory to {os.getcwd()}"
                exit_code = 0
            else:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True)
                stdout, stderr = process.communicate()
                result = stdout if stdout else stderr
                exit_code = process.returncode

            # Format the output (white text on black background)
            formatted_output = f"{format_text('white', bg='black')}{result.strip()}{reset_format()}"
            
            if exit_code != 0:
                debug_suggestion = self.debug_error(command, result, exit_code)
                formatted_output += f"\n\n{format_text('yellow', bold=True)}Debugging Suggestion:{reset_format}\n{debug_suggestion}"

            return formatted_output
        except Exception as e:
            return self.handle_error(str(e), user_input, command)

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
    # Enable tab completion
    readline.parse_and_bind('tab: complete')
    
    # Set up auto-completion function
    def complete(text, state):
        return (glob.glob(os.path.expanduser(text) + '*') + [None])[state]
    
    readline.set_completer(complete)
    readline.set_completer_delims(' \t\n;')

def main():
    assistant = AITerminalAssistant()
    setup_readline()
    
    print(f"{format_text('green', bold=True)}Welcome to the AI-Powered Terminal Assistant!")
    print("This assistant interacts with your real file system. Use with caution.")
    print("You can use natural language queries or standard shell commands.")
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
