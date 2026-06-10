from django import template
from django.utils.safestring import mark_safe
import markdown as md_lib

register = template.Library()

@register.filter
def markdown(value):
    if not value:
        return ""
    return mark_safe(md_lib.markdown(value, extensions=["nl2br"]))
