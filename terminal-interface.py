import os
import subprocess
import sys
import tkinter as tk
from tkinter import font, ttk


class TerminalEmulator(tk.Tk):

    def __init__(self):
        super().__init__()

        self.title("PyTerm - Custom Terminal Emulator")
        self.geometry("900x550")
        self.configure(bg="#0f172a")

        # Command history state
        self.history = []
        self.history_index = 0

        # Current working directory
        self.current_dir = os.getcwd()

        self._build_ui()
        self._bind_events()

        # Display initial welcome prompt
        self.write_output(
            "=== Custom Python Terminal Emulator ===\n", tag="system"
        )
        self.write_output(
            f"Current Directory: {self.current_dir}\nType 'help' or execute commands directly.\n\n",
            tag="system",
        )

    def _build_ui(self):
        # Configure dark aesthetic styles
        self.custom_font = font.Font(family="Consolas", size=11)

        # Main layout frame
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Output Terminal Display
        self.output_text = tk.Text(
            main_frame,
            bg="#020617",
            fg="#e2e8f0",
            insertbackground="#22c55e",
            font=self.custom_font,
            wrap=tk.WORD,
            state=tk.DISABLED,
            bd=0,
            highlightthickness=0,
        )

        # Scrollbar for output
        scrollbar = ttk.Scrollbar(
            main_frame, command=self.output_text.yview
        )
        self.output_text.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.output_text.pack(
            side=tk.TOP, fill=tk.BOTH, expand=True, pady=(0, 6)
        )

        # Text Tags for ANSI/Custom Styling
        self.output_text.tag_config("prompt", foreground="#38bdf8")
        self.output_text.tag_config("system", foreground="#94a3b8")
        self.output_text.tag_config("error", foreground="#f87171")
        self.output_text.tag_config("success", foreground="#4ade80")

        # Input Frame
        input_frame = ttk.Frame(main_frame)
        input_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self.prompt_label = tk.Label(
            input_frame,
            text=self._get_prompt_str(),
            bg="#0f172a",
            fg="#38bdf8",
            font=self.custom_font,
        )
        self.prompt_label.pack(side=tk.LEFT)

        self.entry_var = tk.StringVar()
        self.entry = tk.Entry(
            input_frame,
            textvariable=self.entry_var,
            bg="#1e293b",
            fg="#f8fafc",
            insertbackground="#f8fafc",
            font=self.custom_font,
            bd=1,
            relief=tk.SOLID,
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        self.entry.focus_set()

    def _get_prompt_str(self):
        basename = os.path.basename(self.current_dir) or self.current_dir
        return f"{basename} $ "

    def _bind_events(self):
        self.entry.bind("<Return>", self.on_execute_command)
        self.entry.bind("<Up>", self.on_history_up)
        self.entry.bind("<Down>", self.on_history_down)

    def write_output(self, text, tag=None):
        self.output_text.config(state=tk.NORMAL)
        if tag:
            self.output_text.insert(tk.END, text, tag)
        else:
            self.output_text.insert(tk.END, text)
        self.output_text.see(tk.END)
        self.output_text.config(state=tk.DISABLED)

    def on_execute_command(self, event):
        command = self.entry_var.get().strip()
        self.entry_var.set("")

        if not command:
            return

        # Record History
        self.history.append(command)
        self.history_index = len(self.history)

        # Output entered command
        self.write_output(f"{self._get_prompt_str()}", tag="prompt")
        self.write_output(f"{command}\n")

        # Process Command
        self.process_command(command)

    def process_command(self, cmd_str):
        parts = cmd_str.split()
        base_cmd = parts[0].lower()

        # Built-in internal shell handlers
        if base_cmd == "clear":
            self.output_text.config(state=tk.NORMAL)
            self.output_text.delete("1.0", tk.END)
            self.output_text.config(state=tk.DISABLED)

        elif base_cmd == "cd":
            target = parts[1] if len(parts) > 1 else os.path.expanduser("~")
            try:
                os.chdir(target)
                self.current_dir = os.getcwd()
                self.prompt_label.config(text=self._get_prompt_str())
            except Exception as e:
                self.write_output(
                    f"cd error: {str(e)}\n", tag="error"
                )

        elif base_cmd == "help":
            help_text = (
                "Built-in Commands:\n"
                "  cd <path>    - Change working directory\n"
                "  clear        - Clear console screen\n"
                "  exit         - Exit terminal window\n"
                "  help         - Display this message\n\n"
                "System commands (e.g. ls, dir, ping, python) are executed natively.\n\n"
            )
            self.write_output(help_text, tag="system")

        elif base_cmd == "exit":
            self.destroy()

        else:
            # Fallback to system shell execution
            self.run_system_command(cmd_str)

    def run_system_command(self, cmd_str):
        try:
            # Execute external system process safely
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
            self.write_output(
                f"Execution Error: {str(e)}\n", tag="error"
            )

    def on_history_up(self, event):
        if self.history and self.history_index > 0:
            self.history_index -= 1
            self.entry_var.set(self.history[self.history_index])
            self.entry.icursor(tk.END)
        return "break"  # Prevent default cursor moving left

    def on_history_down(self, event):
        if self.history and self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.entry_var.set(self.history[self.history_index])
            self.entry.icursor(tk.END)
        else:
            self.history_index = len(self.history)
            self.entry_var.set("")
        return "break"


if __name__ == "__main__":
    app = TerminalEmulator()
    app.mainloop()