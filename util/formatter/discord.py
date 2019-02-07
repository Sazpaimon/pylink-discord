import re
from copy import copy

from mistletoe import BaseRenderer
from mistletoe.span_token import SpanToken

from util.formatter.base import MessageBlock, MessageStyle
from util.formatter.markdown import MarkdownMessage


class Underlined(SpanToken):
    precedence = 3
    pattern = re.compile(r"__((?:\\[\s\S]|[^\\])+?)__(?!_)")

# TODO: This doesn't work :(
class DiscordRenderer(BaseRenderer):
    def __init__(self, *extras):
        super().__init__(Underlined, *extras)
        self.parsed_message = []
        self.current_block = MessageBlock()

    def render_strong(self, token):
        token.message_block.style ^= MessageStyle.BOLD
        inner = self.render_inner(token)
        token.message_block = MessageBlock(style=token.message_block.style ^ MessageStyle.BOLD)
        return inner

    def render_emphasis(self, token):
        token.message_block.style ^= MessageStyle.ITALIC
        inner = self.render_inner(token)
        token.message_block = MessageBlock(style=token.message_block.style ^ MessageStyle.ITALIC)
        return inner

    def render_underlined(self, token):
        token.message_block.style ^= MessageStyle.UNDERLINE
        inner = self.render_inner(token)
        token.message_block = MessageBlock(style=token.message_block.style ^ MessageStyle.UNDERLINE)
        return inner

    def render_strikethrough(self, token):
        token.message_block.style ^= MessageStyle.STRIKETHROUGH
        inner = self.render_inner(token)
        token.message_block = MessageBlock(style=token.message_block.style ^ MessageStyle.STRIKETHROUGH)
        return inner

    def render_raw_text(self, token):
        token.message_block.text = token.content
        self.parsed_message.append(copy(token.message_block))
        return token.message_block

    def render_inner(self, token):
        rendered = []
        for child in token.children:
            child.message_block = getattr(token, 'message_block', MessageBlock())
            rendered.append(self.render(child))
        return rendered

    def render(self, token):
        super(DiscordRenderer, self).render(token)
        return self.parsed_message


class DiscordMessage(MarkdownMessage):
    renderer = DiscordRenderer
