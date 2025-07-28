# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Testing
- `python -m pytest` - Run all tests
- `python -m pytest mautrix/types/util/enum_test.py` - Run specific test file
- `python -m pytest --ignore mautrix/util/db/ --ignore mautrix/bridge/` - Skip ignored paths (default config)

### Code Quality
- `black .` - Format code (line length 99, target Python 3.10+)
- `isort .` - Sort imports (black-compatible profile)
- `pre-commit run --all-files` - Run all pre-commit hooks

### Documentation
- `cd docs && make html` - Build Sphinx documentation
- `cd docs && make clean` - Clean documentation build

### Installation
- `pip install -e .` - Install in development mode
- `pip install -e .[test]` - Install with test dependencies
- `pip install -e .[encryption]` - Install with encryption support
- `pip install -r dev-requirements.txt` - Install development tools

## Architecture Overview

### Core Framework Components

**mautrix.api** - Low-level HTTP client for Matrix API requests

**mautrix.types** - Matrix event types, primitives, and serialization utilities using attrs

**mautrix.client** - High-level Matrix client with sync, state management, and E2EE support
- `client.py` - Main client implementation
- `syncer.py` - Event synchronization handling  
- `state_store/` - Room state persistence (memory, file, asyncpg backends)
- `api/` - Client API endpoint wrappers

**mautrix.appservice** - Matrix Application Service framework
- `appservice.py` - Core appservice server
- `api/intent.py` - Intent API for acting as users
- Transaction handling and user/alias queries

**mautrix.bridge** - High-level bridging framework for Matrix bridges
- `bridge.py` - Base bridge class with lifecycle management
- `portal.py` - Base portal class for bridged rooms/chats
- `puppet.py` - Base puppet class for bridged users
- `user.py` - Base user class for bridge users
- `custom_puppet.py` - Double-puppeting support
- `e2ee.py` - End-to-bridge encryption helpers

**mautrix.crypto** - End-to-end encryption implementation
- Uses libolm via python-olm for Olm/Megolm protocols
- `machine.py` - Main crypto state machine
- `store/` - Crypto data persistence (memory, asyncpg backends)
- `attachments/` - File encryption/decryption

**mautrix.util** - Shared utilities
- `async_db/` - Database abstraction (asyncpg, aiosqlite)
- `config/` - YAML configuration management
- `formatter/` - Matrix HTML/Markdown formatting
- `logging/` - Colored logging utilities

### Key Patterns

- **Async/await throughout** - All I/O operations are async
- **attrs dataclasses** - Used for type definitions and serialization
- **State stores** - Pluggable persistence layers (memory/file/database)
- **Intent-based APIs** - AppService intents act as specific users
- **Mixin classes** - Common functionality shared via mixins

### Database Support

- **Primary**: asyncpg (PostgreSQL) with custom migration system
- **Legacy**: SQLAlchemy support in some areas
- **Development**: aiosqlite for testing
- Database schemas defined in `store.py` files with `upgrade.py` migrations

### Configuration

- YAML-based configuration with validation
- Base config classes in `util.config`
- Bridge-specific configs extend `BaseBridgeConfig`

## Project Structure

The codebase follows a layered architecture from low-level HTTP to high-level bridge frameworks. Each major component (`api`, `client`, `appservice`, `bridge`, `crypto`) is self-contained with its own abstractions and can be used independently.