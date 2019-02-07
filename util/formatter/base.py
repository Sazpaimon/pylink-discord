from aenum import Flag, auto


class MessageStyle(Flag):
    NONE = 0
    BOLD = auto()
    ITALIC = auto()
    UNDERLINE = auto()
    COLOR = auto()
    STRIKETHROUGH = auto()


class MessageBlock:
    def __init__(self, text='', style=MessageStyle.NONE, fg=None, bg=None):
        self.text = text
        self.style = style
        self.fg = fg
        self.bg = bg

    def __repr__(self):
        return "({}, ({}, {}), {})".format(self.style, self.fg, self.bg, self.text)

    def __eq__(self, other):
        return (
                isinstance(other, self.__class__) and
                self.style == other.style and
                self.fg == other.fg and
                self.bg == other.bg and
                self.text == other.text
        )
