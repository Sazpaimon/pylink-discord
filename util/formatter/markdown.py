from io import StringIO
from io import StringIO
from typing import List

from aenum import Enum
from mistletoe import HTMLRenderer
from mistletoe.block_token import Document

from util.formatter.base import MessageBlock


class MarkdownMapping(Enum):
    BOLD = '**{message}**'
    ITALIC = '*{message}*'
    UNDERLINE = '__{message}__'
    STRIKETHROUGH = '~~{message}~~'


class MarkdownMessage:
    renderer = HTMLRenderer

    @classmethod
    def parse(cls, text):
        text = StringIO(text)
        with cls.renderer() as renderer:
            rendered = renderer.render(Document(text))
            if isinstance(rendered, str):
                return [MessageBlock(text=rendered)]
            return rendered

    @staticmethod
    def unparse(parsed_text: List[MessageBlock]):
        message = ''
        for message_block in parsed_text:
            block_text = message_block.text
            for style in message_block.style:
                try:
                    block_text = MarkdownMapping[style.name].value.format(message=block_text)
                except KeyError:
                    continue
            message += block_text
        return message
