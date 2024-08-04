import os
import subprocess
import shlex
import getpass
from typing import List, Tuple
import readline
import glob
import requests
import json

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

    def get_accessibility_tools(self):
        accessibility_tools = []
        potential_tools = ['orca', 'festival', 'espeak', 'brltty', 'at-spi2-core']
        
        for tool in potential_tools:
            if subprocess.call(['which', tool], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                accessibility_tools.append(tool)
        
        return accessibility_tools

    def execute_command(self, user_input: str) -> str:
        try:
            # Update current directory
            self.current_directory = os.getcwd()
            
            # Use AI to interpret the user input and convert to a command if necessary
            command = self.command_executor(f"""
            User Input: {user_input}
            Current Directory: {self.current_directory}
            Translate the user input into a SINGLE shell command. Return ONLY the command, nothing else.
            If the input is already a valid shell command, return it as is.
            Do not provide any explanations or comments.
            """).strip()
            
            # Execute the actual command
            if command.startswith("cd "):
                # Handle 'cd' command separately
                path = command.split(" ", 1)[1]
                os.chdir(os.path.expanduser(path))
                result = f"Changed directory to {os.getcwd()}"
            else:
                # Execute other commands using subprocess
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True)
                stdout, stderr = process.communicate()
                result = stdout if stdout else stderr

            # Format the output
            return f"{result.strip()}"
        except Exception as e:
            return self.handle_error(str(e), user_input, command)

    def handle_error(self, error: str, user_input: str, command: str) -> str:
        error_analysis = self.error_handler(f"""
        Error: {error}
        User Input: {user_input}
        Interpreted Command: {command}
        Current Directory: {self.current_directory}
        Provide ONLY a single, simple corrected command. No explanations.
        """)
        
        print(f"Error occurred: {error}")
        print(f"Suggested command: {error_analysis}")
        
        confirmation = input(f"Would you like to execute the suggested command: {error_analysis}? (y/n) ")
        if confirmation.lower() == 'y':
            return self.execute_command(error_analysis)
        
        return "Command execution aborted."

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
    
    print("Welcome to the AI-Powered Terminal Assistant!")
    print("This assistant interacts with your real file system. Use with caution.")
    print("You can use natural language queries or standard shell commands.")
    print("Type 'exit' to quit.")

    while True:
        try:
            user_input = input(f"{os.getcwd()}$ ")
            if user_input.lower() == 'exit':
                break

            # Execute command or process natural language query
            result = assistant.execute_command(user_input)
            print(result)

        except KeyboardInterrupt:
            print("\nKeyboardInterrupt")

    print("Goodbye!")

if __name__ == "__main__":
    main()
