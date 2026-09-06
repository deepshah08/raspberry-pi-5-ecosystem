import pytest
import os
from unittest.mock import MagicMock, patch, AsyncMock, call
import sys, os; sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))); from telegram import Update, User, Message, Chat
from telegram.ext import Application
import httpx

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import sys, os; sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))); from bot import start_command, search_command, briefing_command, status_command, ingest_command, create_app

@pytest.fixture
def mock_context():
    context = MagicMock()
    context.args = []
    return context

@pytest.fixture
def mock_update():
    def _create_update(user_id=12345, text=""):
        update = MagicMock(spec=Update)
        user = User(id=user_id, first_name="Test", is_bot=False)
        chat = Chat(id=user_id, type="private")
        message = MagicMock(spec=Message)
        message.reply_text = AsyncMock()
        message.reply_markdown = AsyncMock()
        message.text = text
        update.effective_user = user
        update.message = message
        return update
    return _create_update

@pytest.fixture(autouse=True)
def setup_env():
    # Setup test env vars
    with patch.dict(os.environ, {
        "TELEGRAM_ADMIN_IDS": "12345,67890",
        "OMNISEARCH_URL": "http://mock-omnisearch:8008",
        "AUDIOBOOKSHELF_URL": "http://mock-audio:13378",
        "CAMERA_INGEST_URL": "http://mock-camera:8080"
    }):
        # Reload env vars inside bot module by modifying its variables directly
        import bot
        bot.TELEGRAM_ADMIN_IDS = [12345, 67890]
        bot.OMNISEARCH_URL = "http://mock-omnisearch:8008"
        bot.AUDIOBOOKSHELF_URL = "http://mock-audio:13378"
        bot.CAMERA_INGEST_URL = "http://mock-camera:8080"
        yield

def test_command_routing():
    app = create_app()
    handlers = app.handlers[0]

    # Verify our handlers are registered
    commands = []
    for handler in handlers:
        if hasattr(handler, 'commands'):
            commands.extend(list(handler.commands))

    assert "start" in commands
    assert "search" in commands
    assert "briefing" in commands
    assert "status" in commands
    assert "ingest" in commands

@pytest.mark.asyncio
async def test_admin_gating(mock_update, mock_context):
    update = mock_update(user_id=99999) # Unauthorized user

    await start_command(update, mock_context)
    update.message.reply_text.assert_called_once_with("Unauthorized access.")

    update.message.reply_text.reset_mock()
    await search_command(update, mock_context)
    update.message.reply_text.assert_called_once_with("Unauthorized access.")

@pytest.mark.asyncio
async def test_search_query(mock_update, mock_context, mocker):
    update = mock_update(user_id=12345)
    mock_context.args = ["sunset", "beach"]

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {"title": "Sunset 1", "timestamp": "1.5", "thumbnail": "http://thumb1.jpg"},
            {"title": "Sunset 2", "timestamp": "3.2", "thumbnail": "http://thumb2.jpg"}
        ]
    }

    # Mock httpx AsyncClient
    mock_get = AsyncMock(return_value=mock_response)

    class MockClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        get = mock_get
        post = AsyncMock()

    mocker.patch('bot.httpx.AsyncClient', return_value=MockClient())

    await search_command(update, mock_context)

    mock_get.assert_called_once_with("http://mock-omnisearch:8008/search", params={"q": "sunset beach"})

    reply_call = update.message.reply_text.call_args[0][0]
    assert "Top matches for 'sunset beach'" in reply_call
    assert "- Sunset 1 (T: 1.5s)" in reply_call
    assert "http://thumb1.jpg" in reply_call

@pytest.mark.asyncio
async def test_briefing_command(mock_update, mock_context, mocker):
    update = mock_update(user_id=12345)

    mock_response = MagicMock()
    mock_response.json.return_value = {"audio_url": "http://mock-audio/briefing.mp3"}

    mock_post = AsyncMock(return_value=mock_response)

    class MockClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        post = mock_post

    mocker.patch('bot.httpx.AsyncClient', return_value=MockClient())

    await briefing_command(update, mock_context)

    mock_post.assert_called_once_with("http://mock-audio:13378/generate_briefing")
    update.message.reply_text.assert_called_once_with("Morning briefing generated: http://mock-audio/briefing.mp3")

@pytest.mark.asyncio
async def test_status_formatting(mock_update, mock_context, mocker):
    update = mock_update(user_id=12345)

    mock_api_class = MagicMock()
    mock_api_instance = mock_api_class.return_value
    mock_api_instance.login = MagicMock()
    mock_api_instance.get_monitors.return_value = [
        {"id": 1, "name": "Plex"},
        {"id": 2, "name": "Pi-hole"},
        {"id": 3, "name": "Down Service"}
    ]

    def mock_get_heartbeats(m_id):
        if m_id == 1:
            return [{"status": 1}]
        elif m_id == 2:
            return [{"status": 1}]
        elif m_id == 3:
            return [{"status": 0}]
        return []

    mock_api_instance.get_heartbeats.side_effect = mock_get_heartbeats
    mock_api_instance.disconnect = MagicMock()

    mocker.patch('bot.UptimeKumaApi', mock_api_class)

    await status_command(update, mock_context)

    mock_api_instance.login.assert_called_once()
    mock_api_instance.get_monitors.assert_called_once()

    # Check that get_heartbeats was called for each monitor id
    mock_api_instance.get_heartbeats.assert_has_calls([call(1), call(2), call(3)])
    mock_api_instance.disconnect.assert_called_once()

    reply_call = update.message.reply_markdown.call_args[0][0]
    assert "📊 **Homelab Status**" in reply_call
    assert "- Plex: 🟢 UP" in reply_call
    assert "- Pi-hole: 🟢 UP" in reply_call
    assert "- Down Service: 🔴 DOWN" in reply_call
    assert "Total: 3" in reply_call
    assert "🟢 2" in reply_call
    assert "🔴 1" in reply_call

@pytest.mark.asyncio
async def test_ingest_command(mock_update, mock_context, mocker):
    update = mock_update(user_id=12345)

    mock_response = MagicMock()
    mock_response.json.return_value = {"status": "Idle", "pending_files": 42}

    mock_get = AsyncMock(return_value=mock_response)

    class MockClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        get = mock_get

    mocker.patch('bot.httpx.AsyncClient', return_value=MockClient())

    await ingest_command(update, mock_context)

    mock_get.assert_called_once_with("http://mock-camera:8080/status")
    update.message.reply_text.assert_called_once_with("Camera Ingest Status: Idle\nPending Files: 42")
