#!/usr/bin/env python3

import asyncio
import logging
import readline
import sys
from pathlib import Path
from typing import Optional

from mautrix.api import HTTPAPI
from mautrix.client import Client
from mautrix.client.state_store.memory import MemoryStateStore
from mautrix.client.state_store.sync import MemorySyncStore
from mautrix.types import (
    EventType,
    MessageEvent,
    MessageType,
    RoomID,
    StateEvent,
    SyncToken,
    TextMessageEventContent,
    UserID,
)
from mautrix.util.logging import TraceLogger


def get_input_with_history(prompt: str) -> str:
    """Get input with readline history support"""
    return input(prompt)


class SimpleChatClient:
    def __init__(
        self,
        homeserver: str,
        user_id: UserID,
        access_token: str,
        device_id: str,
    ):
        self.homeserver = homeserver
        self.user_id = user_id
        self.device_id = device_id
        
        self.log = logging.getLogger("chatcli")
        self.api = HTTPAPI(homeserver, access_token)
        
        # Use memory stores for simplicity
        self.state_store = MemoryStateStore()
        self.sync_store = MemorySyncStore()
        
        self.client = Client(
            api=self.api,
            user_id=user_id,
            device_id=device_id,
            state_store=self.state_store,
            sync_store=self.sync_store,
        )
        
        self.current_room: Optional[RoomID] = None
        self.running = False
        self.sync_task: Optional[asyncio.Task] = None
        self.initial_sync_complete = False
        
        # Event handlers
        self.client.add_event_handler(EventType.ROOM_MESSAGE, self._handle_message)
        self.client.add_event_handler(EventType.ROOM_MEMBER, self._handle_member)

    async def get_room_canonical_alias(self, room_id: RoomID) -> str | None:
        """Get the canonical alias for a room"""
        try:
            canonical_alias = await self.client.get_state(room_id, EventType.ROOM_CANONICAL_ALIAS)
            if canonical_alias and hasattr(canonical_alias, 'alias') and canonical_alias.alias:
                return str(canonical_alias.alias)
        except Exception as e:
            self.log.debug(f"Failed to get canonical alias for {room_id}: {e}")
        return None

    async def get_room_alt_aliases(self, room_id: RoomID) -> list[str]:
        """Get alternative aliases for a room"""
        try:
            alt_aliases = await self.client.get_state(room_id, EventType.ROOM_CANONICAL_ALIAS)
            if alt_aliases and hasattr(alt_aliases, 'alt_aliases') and alt_aliases.alt_aliases:
                return [str(alias) for alias in alt_aliases.alt_aliases]
        except Exception as e:
            self.log.debug(f"Failed to get alt aliases for {room_id}: {e}")
        return []

    async def start(self):
        """Initialize the client and start syncing"""
        self.log.info(f"Starting unencrypted chat client for {self.user_id}")
        
        await self.state_store.open()
        
        # Start syncing
        self.running = True
        self.sync_task = self.client.start(None)  # Don't await - let it run in background
        
        # Give sync a moment to start
        await asyncio.sleep(0.1)
        
        self.log.info("Client started successfully")

    async def stop(self):
        """Stop the client"""
        self.running = False
        
        # Cancel sync task if it's running
        if self.sync_task and not self.sync_task.done():
            self.sync_task.cancel()
            try:
                await self.sync_task
            except asyncio.CancelledError:
                pass
        
        if self.client:
            # Stop syncer if it exists
            if hasattr(self.client, 'stop') and callable(getattr(self.client, 'stop', None)):
                self.client.stop()  # Note: This is not async, it just cancels the sync task
            # Close HTTP session
            if hasattr(self.client, 'api') and self.client.api and hasattr(self.client.api, 'session'):
                if self.client.api.session and not self.client.api.session.closed:
                    await self.client.api.session.close()
        
        # Close stores
        if self.state_store:
            await self.state_store.close()

    async def _handle_message(self, evt: MessageEvent):
        """Handle incoming messages"""
        if evt.sender == self.user_id:
            return
        
        # Don't show messages during initial sync to keep startup clean
        if not self.initial_sync_complete:
            return
        
        # Debug logging
        self.log.debug(f"Received message from {evt.sender} in room {evt.room_id}, current_room={self.current_room}")
        
        sender_name = evt.sender
        
        # Try to get a friendly room name for display
        room_display = evt.room_id
        try:
            room_name = await self.state_store.get_room_name(evt.room_id)
            if room_name:
                room_display = f"{evt.room_id} ({room_name})"
        except Exception:
            pass
            
        content = evt.content
        if content.msgtype == MessageType.TEXT:
            print(f"[{room_display}] {sender_name}: {content.body}")
        elif content.msgtype == MessageType.EMOTE:
            print(f"[{room_display}] * {sender_name} {content.body}")
        else:
            print(f"[{room_display}] {sender_name} sent {content.msgtype}: {content.body}")

    async def _handle_member(self, evt: StateEvent):
        """Handle member events"""
        if self.current_room and evt.room_id == self.current_room:
            member = evt.content
            if hasattr(member, 'membership'):
                action = member.membership.value
                user = evt.state_key
                print(f"[{evt.room_id}] {user} {action}")

    async def join_room(self, room_id: str):
        """Join a room"""
        try:
            # If it's an alias (starts with #), resolve it to the actual room ID
            if room_id.startswith('#'):
                from mautrix.types import RoomAlias
                alias = RoomAlias(room_id)
                resolve_result = await self.client.resolve_room_alias(alias)
                actual_room_id = resolve_result.room_id
                self.log.info(f"Resolved alias {room_id} to room ID {actual_room_id}")
            else:
                actual_room_id = RoomID(room_id)
            
            # Join using the actual room ID
            await self.client.join_room(actual_room_id)
            self.current_room = actual_room_id  # Store the actual room ID
            self.log.info(f"Joined room {actual_room_id} (current_room set to: {self.current_room})")
            
            # Manually ensure membership is set in state store
            from mautrix.types import Membership
            await self.state_store.set_membership(actual_room_id, self.user_id, Membership.JOIN)
            
            # Force a sync to update room state
            await asyncio.sleep(0.5)  # Brief delay for server processing
            
            # Verify we're actually in the room
            joined_rooms = await self.client.get_joined_rooms()
            if actual_room_id not in joined_rooms:
                # Try rejoin if not properly joined
                self.log.warning(f"Room {actual_room_id} not found in joined rooms, attempting rejoin")
                await self.client.join_room(actual_room_id)
                await self.state_store.set_membership(actual_room_id, self.user_id, Membership.JOIN)
                
        except Exception as e:
            self.log.error(f"Failed to join room {room_id}: {e}")

    async def send_message(self, text: str, room_id: Optional[RoomID] = None):
        """Send a text message"""
        target_room = room_id or self.current_room
        if not target_room:
            print("No room selected. Use /join <room_id> first.")
            return
            
        try:
            # Debug: Check membership before sending
            membership = await self.state_store.get_membership(target_room, self.user_id)
            self.log.info(f"Current membership for {self.user_id} in {target_room}: {membership}")
            
            # Verify we're actually in the room according to the server
            joined_rooms = await self.client.get_joined_rooms()
            if target_room not in joined_rooms:
                self.log.warning(f"Room {target_room} not in joined rooms list from server")
                # Try rejoining
                await self.client.join_room(target_room)
                from mautrix.types import Membership
                await self.state_store.set_membership(target_room, self.user_id, Membership.JOIN)
            
            content = TextMessageEventContent(msgtype=MessageType.TEXT, body=text)
            
            # Send the message (unencrypted)
            await self.client.send_message(target_room, content)
            
            self.log.debug(f"Sent unencrypted message to {target_room}")
        except Exception as e:
            self.log.error(f"Failed to send message: {e}")

    async def list_rooms(self):
        """List joined rooms with names and aliases when available"""
        try:
            rooms = await self.client.get_joined_rooms()
            print("Joined rooms:")
            for room_id in rooms:
                try:
                    # Get room name directly from server (MemoryStateStore doesn't have get_room_name)
                    room_name = None
                    try:
                        from mautrix.types import EventType
                        room_state = await self.client.get_state(room_id, EventType.ROOM_NAME)
                        if room_state and hasattr(room_state, 'name'):
                            room_name = room_state.name
                    except Exception:
                        pass
                    
                    # Get canonical alias and alternative aliases
                    room_alias = await self.get_room_canonical_alias(room_id)
                    alt_aliases = await self.get_room_alt_aliases(room_id)
                    
                    # Build display string with room name and aliases
                    display_parts = []
                    if room_name:
                        display_parts.append(room_name)
                    if room_alias:
                        display_parts.append(room_alias)
                    elif alt_aliases:
                        # Use first alternative alias if no canonical alias
                        display_parts.append(alt_aliases[0])
                    
                    if display_parts:
                        display_info = " | ".join(display_parts)
                        print(f"  {room_id} ({display_info})")
                    else:
                        print(f"  {room_id}")
                        
                except Exception as e:
                    self.log.warning(f"Error processing room {room_id}: {e}")
                    print(f"  {room_id}")
        except Exception as e:
            self.log.error(f"Failed to list rooms: {e}")

    async def switch_room(self, room_id_or_alias: str):
        """Switch to different room"""
        try:
            # Handle both room IDs and aliases
            if room_id_or_alias.startswith('#'):
                from mautrix.types import RoomAlias
                alias = RoomAlias(room_id_or_alias)
                resolve_result = await self.client.resolve_room_alias(alias)
                actual_room_id = resolve_result.room_id
                self.log.info(f"Resolved alias {room_id_or_alias} to room ID {actual_room_id}")
            else:
                actual_room_id = RoomID(room_id_or_alias)
            
            # Check if we're in the room
            rooms = await self.client.get_joined_rooms()
            if actual_room_id in rooms:
                self.current_room = actual_room_id
                # Try to get a friendly name for display
                try:
                    room_name = await self.state_store.get_room_name(actual_room_id)
                    if room_name:
                        print(f"Switched to room {actual_room_id} ({room_name})")
                    else:
                        print(f"Switched to room {actual_room_id}")
                except Exception:
                    print(f"Switched to room {actual_room_id}")
            else:
                print(f"Not in room {actual_room_id}. Use /join to join it first.")
        except Exception as e:
            self.log.error(f"Failed to switch room: {e}")

    def show_help(self):
        """Show help message with available commands"""
        print("\nAvailable commands:")
        print("  /help               - Show this help message")
        print("  /join <room_id>     - Join a room (e.g., #room:server.com or !roomid:server.com)")
        print("  /switch <room_id>   - Switch to a different room you've already joined")
        print("  /rooms              - List all joined rooms")
        print("  /quit               - Exit the chat client")
        print("  <message>           - Send message to current room")
        print("\nFeatures:")
        print("  • Unencrypted messaging only (simple and reliable)")
        print("  • Room joining and switching")
        print("  • Real-time message display")
        print("  • Automatic room name resolution")
        print("\nExamples:")
        print("  /join #general:matrix.org")
        print("  /switch !abc123:matrix.org")
        print("  Hello, world!")
        print()


async def main():
    if len(sys.argv) != 5:
        print("Usage: python chatcli.py <homeserver> <user_id> <access_token> <device_id>")
        print("Example: python chatcli.py https://matrix.org @user:matrix.org token DEVICE123")
        sys.exit(1)
        
    homeserver, user_id, access_token, device_id = sys.argv[1:5]
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    
    client = SimpleChatClient(homeserver, UserID(user_id), access_token, device_id)
    
    try:
        await client.start()
        
        # Wait for initial sync to settle before starting interactive session
        print("Simple chat client started! Waiting for initial sync to complete...")
        await asyncio.sleep(2.0)  # Give initial sync time to process
        
        # Mark initial sync as complete to start showing real-time messages
        client.initial_sync_complete = True
        
        print("Ready! Type /help for available commands.")
        print("Note: This client sends and receives unencrypted messages only.")
        print()
        
        # Setup readline for command history
        readline.set_history_length(1000)
        
        # CLI loop
        while client.running:
            try:
                # Show current room with friendly name if available
                room_prompt = "no room"
                if client.current_room:
                    try:
                        room_name = await client.state_store.get_room_name(client.current_room)
                        if room_name:
                            room_prompt = f"{client.current_room} ({room_name})"
                        else:
                            room_prompt = str(client.current_room)
                    except Exception:
                        room_prompt = str(client.current_room)
                
                line = await asyncio.to_thread(get_input_with_history, f"[{room_prompt}] > ")
                line = line.strip()
                
                if not line:
                    continue
                    
                if line == "/quit":
                    break
                elif line == "/help":
                    client.show_help()
                elif line == "/rooms":
                    await client.list_rooms()
                elif line.startswith("/join "):
                    room_id = line[6:].strip()
                    await client.join_room(room_id)
                elif line.startswith("/switch "):
                    room_id = line[8:].strip()
                    await client.switch_room(room_id)
                elif line.startswith("/"):
                    print(f"Unknown command: {line}. Type /help for available commands.")
                else:
                    await client.send_message(line)
                    
            except (EOFError, KeyboardInterrupt):
                break
                
    except Exception as e:
        logging.error(f"Error: {e}", exc_info=True)
    finally:
        try:
            await client.stop()
        except Exception as e:
            logging.error(f"Error during cleanup: {e}")


if __name__ == "__main__":
    asyncio.run(main())