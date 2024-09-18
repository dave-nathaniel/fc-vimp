from django import template

register = template.Library()

@register.filter
def split_str(value, args):
    """Split the string by the given delimiter."""
    args = args.split('|')
    delimiter = args[0] if len(args) > 0 else ' '
    index = int(args[1]) if len(args) > 1 else False
    return value.split(delimiter)[index - 1] if index else value.split(delimiter)