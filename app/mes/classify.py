"""Decide whether each catalogue item is a finished product, an assembly or a component.

The ERP's own item type (Product.erp_type, from a BOM register) beats everything when present. Otherwise
structure beats guesswork, so the rules run in this order:
  1. Anything with its own BOM is an assembly, or a finished product if nothing is made from it.
  2. Anything that is a line on another item's BOM is a component.
  3. Anything customers have ordered is a finished product.
  4. Remaining items: priced items are finished products unless the description reads like a part
     (valve, tubing, cylinder ...) or a spare; unpriced items are components.
More real BOMs mean fewer items fall through to rule 4.
"""
import re

from .bom_import import kind_from_erp_type
from .models import Product

# Words that mark a single part or spare rather than something sold as a system.
PART_WORDS = re.compile(
    r"\b(valve|tubing|tube|tubng|cylinder|fitting|connector|junction|manifold|reservoir|resistor|capacitor|"
    r"diode|transistor|fuse|washer|screw|bolt|nut|bracket|spacer|switch|sensor|bearing|pulley|belt|shaft|"
    r"lamp|bulb|cable|lead|plug|socket|terminal|led|potentiometer|relay|compressor|tool|holder|mount|"
    r"clip|spring|gasket|seal|nozzle|regulator|gauge|filter|silencer|coupling|hose|pipe|adaptor|adapter|"
    r"ammeter|voltmeter|converter|carrier|battery|cell)s?\b", re.I)
# Priced items below CHEAP_RRP read as spares; items at or above SYSTEM_RRP are never treated as parts.
CHEAP_RRP, SYSTEM_RRP = 75, 500
# Words that mark something sold as a kit or system, which beat PART_WORDS.
SYSTEM_WORDS = re.compile(
    r"\b(kit|add-on|addon|trainer|system|training|workcell|course|licen[cs]e|essentials|bundle|rig|bench|"
    r"station|factory|starter|package|pack of \d+ kits)\b", re.I)


def classify_kinds():
    """Set Product.kind for every item. Returns counts by kind."""
    has_bom = set(Product.objects.filter(bom_lines__isnull=False).values_list("pk", flat=True))
    is_child = set(Product.objects.filter(used_in__isnull=False).values_list("pk", flat=True))
    sold = set(Product.objects.filter(sales_lines__isnull=False).values_list("pk", flat=True))

    changed = []
    for product in Product.objects.all():
        erp_kind = kind_from_erp_type(product.erp_type)
        if erp_kind:
            kind = erp_kind
        elif product.pk in has_bom:
            kind = Product.ASSEMBLY if product.pk in is_child else Product.FINISHED
        elif product.pk in is_child:
            kind = Product.COMPONENT
        elif product.pk in sold:
            kind = Product.FINISHED
        elif product.rrp is not None:
            # Cheap items and anything described as a part are spares; big-ticket items are products.
            looks_like_part = (
                (PART_WORDS.search(product.name) or product.rrp < CHEAP_RRP)
                and not SYSTEM_WORDS.search(product.name) and product.rrp < SYSTEM_RRP)
            kind = Product.COMPONENT if looks_like_part else Product.FINISHED
        else:
            kind = Product.COMPONENT
        if kind != product.kind:
            product.kind = kind
            changed.append(product)
    Product.objects.bulk_update(changed, ["kind"], batch_size=500)
    return {k: Product.objects.filter(kind=k).count() for k in (Product.FINISHED, Product.ASSEMBLY, Product.COMPONENT)}
