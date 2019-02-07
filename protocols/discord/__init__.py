from gevent import monkey

monkey.patch_ssl()
from protocols.discord.protocol import PyLinkDiscordProtocol

Class = PyLinkDiscordProtocol
