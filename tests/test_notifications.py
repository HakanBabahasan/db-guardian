"""
Bildirim Testleri - src/notifications/notifier.py

Gercek Slack/SMTP baglantisi gerektirmez.
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

for _key in ("SLACK_WEBHOOK_URL", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
    os.environ.pop(_key, None)


class TestNotificationsUnconfigured:

    async def test_notify_does_not_raise_without_config(self):
        from src.notifications.notifier import NotificationService
        svc = NotificationService()
        await svc.notify(event="BLOCK", job_id="job-001", actor="dev1", details={"sql": "DROP"})

    async def test_send_slack_returns_false_when_no_webhook(self):
        from src.notifications.notifier import NotificationService
        svc = NotificationService()
        with patch("src.notifications.notifier.settings") as mock_settings:
            mock_settings.slack_webhook_url = ""
            result = await svc.send_slack("test message")
            assert result is False

    def test_send_email_returns_false_when_no_smtp(self):
        from src.notifications.notifier import NotificationService
        svc = NotificationService()
        with patch("src.notifications.notifier.settings") as mock_settings:
            mock_settings.smtp_host = ""
            mock_settings.smtp_to = ""
            result = svc.send_email("subject", "body")
            assert result is False


class TestSlackIntegration:

    async def test_send_slack_posts_when_webhook_configured(self):
        from src.notifications.notifier import NotificationService
        svc = NotificationService()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("src.notifications.notifier.settings") as mock_settings, \
             patch("src.notifications.notifier.httpx.AsyncClient", return_value=mock_client):
            mock_settings.slack_webhook_url = "https://hooks.slack.com/services/FAKE"
            result = await svc.send_slack("merhaba!")
            assert result is True
            mock_client.post.assert_called_once()

    async def test_slack_failure_does_not_raise(self):
        from src.notifications.notifier import NotificationService
        svc = NotificationService()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("src.notifications.notifier.settings") as mock_settings, \
             patch("src.notifications.notifier.httpx.AsyncClient", return_value=mock_client):
            mock_settings.slack_webhook_url = "https://hooks.slack.com/FAKE"
            result = await svc.send_slack("test")
            assert result is False


class TestNotifyEvents:

    def test_block_event_triggers_notification(self):
        from src.notifications.notifier import NOTIFY_EVENTS
        assert "BLOCK" in NOTIFY_EVENTS

    def test_manual_review_event_triggers_notification(self):
        from src.notifications.notifier import NOTIFY_EVENTS
        assert "MANUAL_REVIEW" in NOTIFY_EVENTS

    def test_breakglass_approved_triggers_notification(self):
        from src.notifications.notifier import NOTIFY_EVENTS
        assert "BREAKGLASS_APPROVED" in NOTIFY_EVENTS

    def test_normal_execute_does_not_notify(self):
        from src.notifications.notifier import NOTIFY_EVENTS
        assert "EXECUTE" not in NOTIFY_EVENTS

    async def test_notify_skips_non_notify_event(self):
        from src.notifications.notifier import NotificationService
        svc = NotificationService()
        with patch.object(svc, "send_slack", new_callable=AsyncMock) as mock_slack:
            await svc.notify(event="EXECUTE", job_id="j1", actor="dev1")
            mock_slack.assert_not_called()

    async def test_notify_calls_send_slack_for_block_event(self):
        from src.notifications.notifier import NotificationService
        svc = NotificationService()
        with patch.object(svc, "send_slack", new_callable=AsyncMock) as mock_slack, \
             patch.object(svc, "send_email", return_value=False):
            mock_slack.return_value = False
            await svc.notify(event="BLOCK", job_id="j1", actor="dev1")
            mock_slack.assert_called_once()