class Backend:
    """Turns remote commands into real keyboard and mouse input.

    Subclasses implement move, scroll, button, click, hotkey and type_text.
    Calls are serialized by the server, so backends needn't be thread-safe.
    """

    name = "?"
    holding = False  # left button held down via the Hold button

    def mouse_down(self):
        if not self.holding:
            self.button("left", True)
            self.holding = True

    def mouse_up(self):
        if self.holding:
            self.button("left", False)
            self.holding = False

    def close(self):
        pass
