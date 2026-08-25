from django.core.management.base import BaseCommand

from rag_engine import sync_wordpress_content


class Command(BaseCommand):
    help = (
        "Sync Dragon Finance WordPress content "
        "into the RAG vector store"
    )

    def handle(self, *args, **options):
        summary = sync_wordpress_content()

        self.stdout.write(
            self.style.SUCCESS(
                str(summary)
            )
        )