from itertools import zip_longest
from typing import List

from aenum import Enum

from util.formatter.base import MessageBlock, MessageStyle


class MessageControlChars(Enum):
    BOLD = '\x02'
    COLOR = '\x03'
    RESET = '\x0f'
    SWAP = '\x16'
    ITALIC = '\x1d'
    UNDERLINE = '\x1f'

    @property
    def is_style(self):
        return self in [self.BOLD, self.COLOR, self.ITALIC, self.UNDERLINE]


class IrcMessage:
    @staticmethod
    def parse(text):
        parsed_message = []
        current_block = MessageBlock()
        parse_color = parse_fg = parse_bg = False
        color_fg = color_bg = None
        for (character, next_character) in zip_longest(text, text[1:]):
            try:
                control_character = MessageControlChars(character)
            except ValueError:
                if parse_color:
                    if character.isnumeric() and parse_fg and len(color_fg) < 2:
                        color_fg += character
                        character = ''
                    elif character == ',':
                        parse_fg = False

                        if next_character.isnumeric():
                            parse_bg = True
                            character = ''
                    elif character.isnumeric() and parse_bg and len(color_bg) < 2:
                        color_bg += character
                        character = ''
                    else:
                        if color_fg:
                            current_block.fg = int(color_fg)

                        if color_bg:
                            current_block.bg = int(color_bg)

                        parse_color = False
                        parse_fg = False
                        parse_bg = False

                        if current_block.fg is None and current_block.bg is None:
                            current_block.style ^= MessageStyle.COLOR

                if character:
                    current_block.text += character

                    if not next_character:
                        parsed_message.append(current_block)
                continue

            if current_block.text:
                parsed_message.append(current_block)

            if not next_character:
                break

            if control_character.is_style:
                new_block = MessageBlock(
                    style=current_block.style ^ MessageStyle[control_character.name],
                    fg=current_block.fg,
                    bg=current_block.bg)
            elif control_character == MessageControlChars.SWAP:
                new_block = MessageBlock(
                    style=current_block.style,
                    fg=current_block.bg,
                    bg=current_block.fg)
            else:
                new_block = MessageBlock()

            current_block = new_block

            if current_block.style & MessageStyle.COLOR == MessageStyle.COLOR:
                parse_color = parse_fg = True
                color_fg = color_bg = ''
            else:
                parse_color = False
                current_block.fg = None
                current_block.bg = None

        return parsed_message

    @staticmethod
    def unparse(parsed_text: List[MessageBlock]):
        message = ''
        for message_block in parsed_text:
            closing_block = ''
            for style in message_block.style:
                message += MessageControlChars[style.name].value
                closing_block += MessageControlChars[style.name].value
                if style == MessageStyle.COLOR:
                    if message_block.fg:
                        message += str(message_block.fg)
                    if message_block.bg:
                        message += ',{}'.format(message_block.bg)
            message += '{}{}'.format(message_block.text, closing_block)
        return message
