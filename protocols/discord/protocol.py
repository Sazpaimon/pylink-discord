from collections import defaultdict

from disco.bot import Bot, BotConfig
from disco.client import Client, ClientConfig
from disco.util.logging import setup_logging
from pylinkirc.classes import *
from pylinkirc.log import log
from pylinkirc.protocols.clientbot import ClientbotWrapperProtocol

from protocols.discord.bot import DiscordBotPlugin
from util.formatter.discord import DiscordMessage
from util.formatter.irc import IrcMessage


class DiscordServer(ClientbotWrapperProtocol):
    def __init__(self, name, parent, server_id):
        conf.conf['servers'][name] = {}
        super().__init__(name)
        self.virtual_parent = parent
        self.sidgen = PUIDGenerator('DiscordInternalSID')
        self.uidgen = PUIDGenerator('PUID')
        self.sid = str(server_id)
        self.servers[self.sid] = Server(self, None, '0.0.0.0', internal=False, desc=name)

    def _init_vars(self):
        super()._init_vars()
        self.casemapping = 'ascii'  # TODO: investigate utf-8 support
        self.cmodes = {'op': 'o', 'halfop': 'h', 'voice': 'v', 'owner': 'q', 'admin': 'a',
                       '*A': '', '*B': '', '*C': '', '*D': ''}

    def message(self, source, target, text, notice=False):
        """Sends messages to the target."""
        if target in self.users:
            # Find or create the DM channel
            try:
                discord_target = self.channels[self.users[target].dm_channel].discord_channel
            except (KeyError, AttributeError):
                dm_channel = discord_target = self.users[target].discord_user.user.open_dm()
                self.users[target].dm_channel = str(dm_channel.id)
                self.channels[str(dm_channel)] = Channel(self, name=str(dm_channel))
                self.channels[str(dm_channel)].discord_channel = dm_channel
        else:
            discord_target = self.channels[target].discord_channel

        message_data = {'target': discord_target, 'sender': source}
        parsed_message = IrcMessage.parse(text)
        if self.pseudoclient and self.pseudoclient.uid == source:
            message_data['text'] = DiscordMessage.unparse(parsed_message)
            self.virtual_parent.message_queue.put_nowait(message_data)
            return

        if not self.is_channel(target):
            self.call_hooks([source, 'CLIENTBOT_MESSAGE', {'target': target, 'is_notice': notice, 'text': text}])
            return

        try:
            text = DiscordMessage.unparse(parsed_message)
            remotenet, remoteuser = self.users[source].remote
            channel_webhooks = discord_target.get_webhooks()
            if channel_webhooks:
                message_data['webhook'] = channel_webhooks[0]
                message_data.update(self.get_user_webhook_data(remoteuser, remotenet))
            message_data['text'] = text
            self.virtual_parent.message_queue.put_nowait(message_data)
        except (AttributeError, KeyError):
            self.call_hooks([source, 'CLIENTBOT_MESSAGE', {'target': target, 'is_notice': notice, 'text': text}])

    def join(self, client, channel):
        """STUB: Joins a user to a channel."""
        self._channels[channel].users.add(client)
        self.users[client].channels.add(channel)

        log.debug('(%s) join: faking JOIN of client %s/%s to %s', self.name, client,
                  self.get_friendly_name(client), channel)
        self.call_hooks([client, 'CLIENTBOT_JOIN', {'channel': channel}])

    def send(self, data, queue=True):
        pass

    def get_user_webhook_data(self, uid, network):
        user = world.networkobjects[network].users[uid]
        return {
            'username': "{} (IRC @ {})".format(user.nick, network)
        }


class PyLinkDiscordProtocol(PyLinkNetworkCoreWithUtils):
    def __init__(self, *args, **kwargs):
        from gevent import monkey
        monkey.patch_all()

        super().__init__(*args, **kwargs)
        self._hooks_queue = queue.Queue()

        if 'token' not in self.serverdata:
            raise ProtocolError("No API token defined under server settings")
        self.client_config = ClientConfig({'token': self.serverdata['token']})
        self.client = Client(self.client_config)
        self.bot_config = BotConfig()
        self.bot = Bot(self.client, self.bot_config)
        self.bot_plugin = DiscordBotPlugin(self, self.bot, self.bot_config)
        self.bot.add_plugin(self.bot_plugin)
        setup_logging(level='DEBUG')
        self._children = {}
        self.message_queue = queue.Queue()

    def _message_builder(self):
        current_channel_senders = {}
        joined_messages = defaultdict(dict)
        while not self._aborted.is_set():
            try:
                message = self.message_queue.get(timeout=0.1)
                message_text = message.pop('text', '')
                channel = message.pop('target')
                current_sender = current_channel_senders.get(channel, None)

                if current_sender != message['sender']:
                    self.flush(channel, joined_messages[channel])
                    joined_messages[channel] = message

                current_channel_senders[channel] = message['sender']

                joined_message = joined_messages[channel].get('text', '')
                joined_messages[channel]['text'] = joined_message + "\n{}".format(message_text)
            except queue.Empty:
                for channel, message_info in joined_messages.items():
                    self.flush(channel, message_info)
                joined_messages = defaultdict(dict)
                current_channel_senders = {}

    def flush(self, channel, message_info):
        message_text = message_info.pop('text', '').strip()
        if message_text:
            if message_info.get('username'):
                message_info['webhook'].execute(
                    content=message_text,
                    username=message_info['username'],
                    avatar_url=message_info.get('avatar'),
                )
            else:
                channel.send_message(message_text)

    def _process_hooks(self):
        """Loop to process incoming hook data."""
        while not self._aborted.is_set():
            data = self._hooks_queue.get()
            if data is None:
                log.debug('(%s) Stopping queue thread due to getting None as item', self.name)
                break
            elif self not in world.networkobjects.values():
                log.debug('(%s) Stopping stale queue thread; no longer matches world.networkobjects', self.name)
                break

            subserver, data = data
            if subserver not in world.networkobjects:
                log.error('(%s) Not queuing hook for subserver %r no longer in networks list.',
                          self.name, subserver)
            elif subserver in self._children:
                self._children[subserver].call_hooks(data)

    def _add_hook(self, subserver, data):
        """
        Pushes a hook payload for the given subserver.
        """
        if subserver not in self._children:
            raise ValueError("Unknown subserver %s" % subserver)
        self._hooks_queue.put_nowait((
            subserver,
            data
        ))

    def _create_child(self, name, server_id):
        """
        Creates a virtual network object for a server with the given name.
        """
        if name in world.networkobjects:
            raise ValueError("Attempting to reintroduce network with name %r" % name)
        child = DiscordServer(name, self, server_id)
        world.networkobjects[name] = self._children[name] = child
        return child

    def _remove_child(self, name):
        """
        Removes a virtual network object with the given name.
        """
        self._add_hook(name, [None, 'PYLINK_DISCONNECT', {}])
        del self._children[name]
        del world.networkobjects[name]

    def connect(self):
        self._aborted.clear()

        self._queue_thread = threading.Thread(name="Queue thread for %s" % self.name,
                                              target=self._process_hooks, daemon=True)
        self._queue_thread.start()

        self._message_thread = threading.Thread(name="Message thread for %s" % self.name,
                                                target=self._message_builder, daemon=True)
        self._message_thread.start()

        self.client.run()

    def websocket_close(self, *_, **__):
        return self.disconnect()

    def disconnect(self):
        self._aborted.set()

        self._pre_disconnect()

        log.debug('(%s) Killing hooks handler', self.name)
        try:
            # XXX: queue.Queue.queue isn't actually documented, so this is probably not reliable in the long run.
            with self._hooks_queue.mutex:
                self._hooks_queue.queue[0] = None
        except IndexError:
            self._hooks_queue.put(None)

        children = self._children.copy()
        for child in children:
            self._remove_child(child)

        if world.shutting_down.is_set():
            self.bot.client.gw.shutting_down = True
        log.debug('(%s) Sending Discord logout', self.name)
        self.bot.client.gw.session_id = None
        self.bot.client.gw.ws.close()

        self._post_disconnect()
