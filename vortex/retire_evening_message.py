"""One-time deletion of the Telegram post explicitly selected for retirement."""
from datetime import datetime, timedelta, timezone

from .bot import STATE, read_state
from .telegram import TelegramClient, TelegramDeliveryError


def main():
    receipt = read_state(STATE / 'deliveries.json').get('2026-11-17:evening', {})
    message_id = receipt.get('telegram_message_id')
    if (message_id != 463 or not receipt.get('delivered')
            or receipt.get('telegram_verification_source') != 'telegram-bot-api'):
        raise RuntimeError('Targeted Evening Creator Watch receipt could not be verified')
    age = datetime.now(timezone.utc) - datetime.fromisoformat(receipt['telegram_delivered_at'])
    if not timedelta(0) <= age < timedelta(hours=48):
        raise RuntimeError('Targeted Telegram post is outside the Bot API deletion window')

    client = TelegramClient()
    client.verify_destination()
    result = client._post('deleteMessage', {'chat_id': client.chat_id, 'message_id': message_id})
    if result.get('result') is not True:
        raise TelegramDeliveryError('Telegram did not acknowledge deleting Evening Creator Watch')
    print(f'Telegram confirmed deletion of Evening Creator Watch message {message_id}')


if __name__ == '__main__':
    main()
