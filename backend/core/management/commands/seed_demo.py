from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import Conversation, Message, Participant, Preference, User


class Command(BaseCommand):
    help = "Create clearly marked local demonstration accounts and conversations. Never run in production."

    def handle(self, *args, **options):
        users = []
        for name in ("Alice", "Bob", "Charlie"):
            email = f"{name.lower()}@example.test"
            user = User.objects.filter(email=email).first()
            if not user:
                user = User.objects.create_user(email, "DemoPass123!", display_name=name)
                Preference.objects.get_or_create(user=user)
            users.append(user)
        alice, bob, charlie = users
        conversation = Conversation.objects.filter(title="Demo: Design team", created_by=alice).first()
        if not conversation:
            conversation = Conversation.objects.create(title="Demo: Design team", is_group=True, created_by=alice)
            for user in users:
                Participant.objects.create(conversation=conversation, user=user, role="admin" if user == alice else "member")
            Message.objects.create(conversation=conversation, sender=alice, body="[DEMO] Welcome to MyChat!", status="sent", sent_at=timezone.now())
            Message.objects.create(conversation=conversation, sender=bob, body="[DEMO] This is sample data. Feel free to test real internal messaging here.", status="sent", sent_at=timezone.now())
        self.stdout.write(self.style.SUCCESS("Demo users: alice@example.test, bob@example.test, charlie@example.test / DemoPass123!"))
