from django.core.management.base import BaseCommand, CommandError

from mes.datapacks import load_pack
from mes.demo.finish import finish_catalogue, sync_basics


class Command(BaseCommand):
    help = ("Load or refresh real data from the pack's files. Unlike `seed` this NEVER wipes anything, so it is the "
            "command to use on a production database: it adds and updates records, replaces the BOM of each "
            "parent present in an imported explosion, and leaves work orders, units, defects and users alone.")

    def add_arguments(self, parser):
        parser.add_argument("--pack", help="data pack in mes/datapacks to load (default: the MES_DATA_PACK setting)")

    def handle(self, *args, pack=None, **options):
        pack = load_pack(pack)
        if not hasattr(pack, "load_real_data"):
            raise CommandError(f"The pack '{pack.__name__.rsplit('.', 1)[-1]}' has no load_real_data function.")
        self.stdout.write(f"Data pack: {pack.__name__.rsplit('.', 1)[-1]} (refreshing, nothing is deleted)")
        sync_basics(pack)
        pack.load_real_data(self)
        finish_catalogue(pack, self)
        self.stdout.write(self.style.SUCCESS("Real data refreshed."))
