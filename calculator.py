import tkinter as tk
from tkinter import font
import ast
import operator

# Safe evaluation mapping for arithmetic operations
OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def safe_eval(expression: str) -> str:
    """Evaluate a mathematical expression safely."""
    try:
        node = ast.parse(expression, mode="eval")
        return str(_evaluate_ast(node.body))
    except Exception:
        return "Error"


def _evaluate_ast(node):
    if isinstance(node, ast.BinOp):
        left = _evaluate_ast(node.left)
        right = _evaluate_ast(node.right)
        op = type(node.op)
        if op in OPERATORS:
            return OPERATORS[op](left, right)
    elif isinstance(node, ast.UnaryOp):
        operand = _evaluate_ast(node.operand)
        op = type(node.op)
        if op in OPERATORS:
            return OPERATORS[op](operand)
    elif isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
    elif isinstance(node, ast.Expr):
        return _evaluate_ast(node.value)
    raise ValueError("Unsupported expression")


class CalculatorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Calculator")
        self.root.resizable(False, False)
        self.expression = ""
        self._build_ui()

    def _build_ui(self) -> None:
        display_font = font.Font(size=24, weight="bold")
        button_font = font.Font(size=18)

        self.display = tk.Entry(
            self.root,
            font=display_font,
            borderwidth=2,
            relief="ridge",
            justify="right",
            width=16,
        )
        self.display.grid(row=0, column=0, columnspan=4, padx=10, pady=10, ipady=10)
        self.display.insert(0, "0")
        self.display.configure(state="readonly")

        buttons = [
            ("C", 1, 0), ("÷", 1, 1), ("×", 1, 2), ("←", 1, 3),
            ("7", 2, 0), ("8", 2, 1), ("9", 2, 2), ("-", 2, 3),
            ("4", 3, 0), ("5", 3, 1), ("6", 3, 2), ("+", 3, 3),
            ("1", 4, 0), ("2", 4, 1), ("3", 4, 2), ("=", 4, 3),
            ("0", 5, 0), (".", 5, 1), ("±", 5, 2),
        ]

        for (text, row, column) in buttons:
            button = tk.Button(
                self.root,
                text=text,
                font=button_font,
                width=4,
                height=2,
                command=lambda t=text: self._on_button_click(t),
            )
            button.grid(row=row, column=column, padx=5, pady=5)

        # Expand zero to span two columns
        zero_button = self.root.grid_slaves(row=5, column=0)[0]
        zero_button.grid_configure(columnspan=2, sticky="we")

    def _on_button_click(self, label: str) -> None:
        if label == "C":
            self.expression = ""
        elif label == "←":
            self.expression = self.expression[:-1]
        elif label == "=":
            self._calculate_result()
            return
        elif label == "±":
            self._toggle_sign()
        else:
            self._append_to_expression(label)

        self._update_display()

    def _append_to_expression(self, value: str) -> None:
        if value == "×":
            value = "*"
        elif value == "÷":
            value = "/"

        if not self.expression and value in "+-*/":
            return

        self.expression += value

    def _toggle_sign(self) -> None:
        if self.expression.startswith("-"):
            self.expression = self.expression[1:]
        else:
            self.expression = f"-{self.expression}" if self.expression else "-"

    def _calculate_result(self) -> None:
        if not self.expression:
            return
        result = safe_eval(self.expression)
        self.expression = result if result != "Error" else ""
        self._update_display(result)

    def _update_display(self, text: str | None = None) -> None:
        value = text if text is not None else self.expression
        if not value:
            value = "0"
        self.display.configure(state="normal")
        self.display.delete(0, tk.END)
        self.display.insert(0, value)
        self.display.configure(state="readonly")


if __name__ == "__main__":
    root = tk.Tk()
    app = CalculatorApp(root)
    root.mainloop()
