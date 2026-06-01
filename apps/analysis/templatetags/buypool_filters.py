from django import template

register = template.Library()


@register.filter(is_safe=True)
def to_yi(value):
    if value is None:
        return '-'
    yi = value / 100_000_000
    return f'{yi:,.2f} 億'


@register.filter
def dictget(d, key):
    return d.get(key)
