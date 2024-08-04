# AI Terminal Assistant

## Author
David Hamner

## Description
AI Terminal Assistant is an intelligent command-line interface that enhances the traditional terminal experience with AI-powered features. It interprets natural language queries, executes commands, and provides context-aware debugging assistance.

## Features
- Natural language command interpretation
- Execution of shell commands
- Intelligent error debugging with suggestions
- Command history tracking
- Color-coded output for improved readability
- Tab completion for file paths

## Requirements
- Python 3.x
- Ollama (with a suitable language model, default is "llama3.1:8b")
- `requests` library

## Installation
1. Clone this repository:
   ```
   git clone https://github.com/your-username/ai-terminal-assistant.git
   cd ai-terminal-assistant
   ```

2. Install the required Python library:
   ```
   pip install requests
   ```

3. Ensure Ollama is installed and running with the appropriate model.

## Usage
Run the script using Python:

```
python3 main.py
```

Once started, you can interact with the AI Terminal Assistant using natural language queries or standard shell commands. Type 'exit' to quit the application.

## License
This project is licensed under the GNU General Public License v3.0 (GPL-3.0). See the [LICENSE](LICENSE) file for details.

## Acknowledgements
- This project was developed with the assistance of Claude.ai, an AI language model by Anthropic.

## Disclaimer
This assistant interacts with your real file system. Use with caution and always verify commands before execution, especially when dealing with important data or system files.

## Contributing
Contributions, issues, and feature requests are welcome. Feel free to check issues page if you want to contribute.
