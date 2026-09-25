import os
import subprocess
import sys
import tkinter as tk
from tkinter import font


class TerminalEmulator(tk.Tk):

    def __init__(self):
        super().__init__()

        self.title("Terminal")
        self.geometry("900x550")
        self.configure(bg="#000000")

        # Command history state
        self.history = []
        self.history_index = 0

        # Current working directory
        self.current_dir = os.getcwd()

        self._build_ui()
        self._bind_events()

        # Display initial welcome prompt
        self.write_output("Welcome to PyTerm\nType 'help' for built-in commands.\n\n")
        self._insert_prompt()

    def _build_ui(self):
        # Monospace terminal font
        self.custom_font = font.Font(family="Consolas", size=11)

        # Single continuous Text widget acting as screen & buffer
        self.terminal = tk.Text(
            self,
            bg="#0c0c0c",            # Classic dark background
            fg="#cccccc",            # Neutral white/gray text
            insertbackground="#cccccc",  # Caret color
            insertwidth=8,           # Thicker, block-like cursor
            font=self.custom_font,
            wrap=tk.CHAR,
            bd=0,
            highlightthickness=0,
            padx=10,
            pady=10,
        )
        self.terminal.pack(fill=tk.BOTH, expand=True)

        # Text Tags for styling elements inline
        self.terminal.tag_config("prompt", foreground="#00ff00", font=self.custom_font)
        self.terminal.tag_config("error", foreground="#ff5555")

        # Mark position to track where editable user input starts
        self.terminal.mark_set("input_start", tk.END)
        self.terminal.mark_gravity("input_start", tk.LEFT)

    def _get_prompt_str(self):
        basename = os.path.basename(self.current_dir) or self.current_dir
        return f"{basename} $ "

    def _insert_prompt(self):
        self.terminal.insert(tk.END, self._get_prompt_str(), "prompt")
        self.terminal.mark_set("input_start", "end-1c")
        self.terminal.see(tk.END)

    def _bind_events(self):
        # Intercept typing & control keys directly in the Text widget
        self.terminal.bind("<Return>", self.on_execute_command)
        self.terminal.bind("<Up>", self.on_history_up)
        self.terminal.bind("<Down>", self.on_history_down)
        self.terminal.bind("<BackSpace>", self.on_backspace)
        self.terminal.bind("<Key>", self.on_key_press)
        self.terminal.bind("<Button-1>", self.on_click)

    def write_output(self, text, tag=None):
        if tag:
            self.terminal.insert(tk.END, text, tag)
        else:
            self.terminal.insert(tk.END, text)
        self.terminal.see(tk.END)

    def on_click(self, event):
        # Ensure focus stays on the terminal and cursor doesn't drift into history
        self.after(1, lambda: self.terminal.mark_set("insert", tk.END))

    def on_key_press(self, event):
        # Prevent editing text before the prompt
        if self.terminal.compare("insert", "<", "input_start"):
            self.terminal.mark_set("insert", tk.END)

    def on_backspace(self, event):
        # Prevent backspacing past the active prompt
        if self.terminal.compare("insert", "<=", "input_start"):
            return "break"

    def on_execute_command(self, event):
        # Extract command typed after input_start
        command = self.terminal.get("input_start", "end-1c").strip()
        self.terminal.insert(tk.END, "\n")

        if command:
            self.history.append(command)
            self.history_index = len(self.history)
            self.process_command(command)
        else:
            self._insert_prompt()

        return "break"

    def process_command(self, cmd_str):
        parts = cmd_str.split()
        base_cmd = parts[0].lower()

        if base_cmd == "clear":
            self.terminal.delete("1.0", tk.END)
            self._insert_prompt()
            return

        elif base_cmd == "cd":
            target = parts[1] if len(parts) > 1 else os.path.expanduser("~")
            try:
                os.chdir(target)
                self.current_dir = os.getcwd()
            except Exception as e:
                self.write_output(f"cd error: {str(e)}\n", tag="error")

        elif base_cmd == "help":
            help_text = (
                "Built-in Commands:\n"
                "  cd <path>    - Change working directory\n"
                "  clear        - Clear console screen\n"
                "  exit         - Exit terminal window\n"
                "  help         - Display this message\n\n"
            )
            self.write_output(help_text)

        elif base_cmd == "exit":
            self.destroy()
            return

        else:
            self.run_system_command(cmd_str)

        self._insert_prompt()

    def run_system_command(self, cmd_str):
        try:
            process = subprocess.Popen(
                cmd_str,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.current_dir,
                text=True,
            )
            stdout, stderr = process.communicate()

            if stdout:
                self.write_output(stdout)
            if stderr:
                self.write_output(stderr, tag="error")

        except Exception as e:
            self.write_output(f"Execution Error: {str(e)}\n", tag="error")

    def on_history_up(self, event):
        if self.history and self.history_index > 0:
            self.history_index -= 1
            self._replace_input(self.history[self.history_index])
        return "break"

    def on_history_down(self, event):
        if self.history and self.history_index < len(self.history) - 1:
            self.history_index += 1
            self._replace_input(self.history[self.history_index])
        else:
            self.history_index = len(self.history)
            self._replace_input("")
        return "break"

    def _replace_input(self, new_text):
        self.terminal.delete("input_start", tk.END)
        self.terminal.insert("input_start", new_text)
        self.terminal.mark_set("insert", tk.END)


if __name__ == "__main__":
    app = TerminalEmulator()
    app.mainloop()