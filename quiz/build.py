import enum
import json
import typing as t
from dataclasses import dataclass, replace
from functools import singledispatch
from operator import methodcaller
from textwrap import indent

from .utils import FrozenDict

import snug

# TODO: __slots__

INDENT = "  "
NEWLINE = ""

gql = methodcaller("__gql__")


FieldName = str
"""a valid GraphQL fieldname"""


@singledispatch
def argument_as_gql(obj):
    raise TypeError("cannot serialize to GraphQL: {}".format(type(obj)))


argument_as_gql.register(str, '"{}"'.format)
argument_as_gql.register(int, str)

# TODO: float, with exponent form


# TODO: make specific enum subclass to ensure
# only graphql compatible enums are set?
@argument_as_gql.register(enum.Enum)
def _enum_to_gql(obj):
    return obj.value


@dataclass(frozen=True, init=False)
class Field:
    name: FieldName
    kwargs: FrozenDict = FrozenDict()
    # TODO: unify with `NestedObject`?
    # - alias
    # - selection_set
    # - directives

    def __init__(self, name, kwargs=()):
        self.__dict__.update({
            'name': name,
            'kwargs': FrozenDict(kwargs)
        })

    def __gql__(self):
        if self.kwargs:
            joined = ", ".join(
                "{}: {}".format(k, argument_as_gql(v))
                for k, v in self.kwargs.items()
            )
            return f"{self.name}({joined})"
        else:
            return self.name

    def __repr__(self):
        return f".{self.name}"


@dataclass(frozen=True)
class NestedObject:
    attr:   Field
    fields: t.Tuple['Fieldlike']

    def __repr__(self):
        return "Nested({}, {})".format(self.attr.name, list(self.fields))

    def __gql__(self):
        return "{} {{\n{}\n}}".format(
            gql(self.attr), indent('\n'.join(map(gql, self.fields)),
                                   INDENT)
        )


Fieldlike = t.Union[Field, NestedObject]


class Error(Exception):
    """an error relating to building a query"""


# TODO: ** operator for specifying fragments
@dataclass(repr=False, frozen=True, init=False)
class SelectionSet:
    """A "magic" selection set builder"""
    # the attribute needs to have a dunder name to prevent
    # comflicts with GraphQL field names
    __fields__: t.Tuple[Fieldlike]
    # according to the GQL spec: this is ordered

    def __init__(self, *fields):
        self.__dict__['__fields__'] = fields

    @classmethod
    def _make(cls, fields):
        return cls(*fields)

    def __getattr__(self, name):
        return SelectionSet._make(self.__fields__ + (Field(name, {}), ))

    def __getitem__(self, selection):
        # TODO: check duplicate fieldnames
        try:
            *rest, target = self.__fields__
        except ValueError:
            raise Error('cannot select fields form empty field list')
        if isinstance(selection, str):
            # parse the string?
            # selection = RawGraphQL(dedent(selection).strip())
            raise NotImplementedError('raw GraphQL not yet implemented')
        elif isinstance(selection, SelectionSet):
            assert len(selection.__fields__) >= 1
        return SelectionSet._make(
            tuple(rest) + (NestedObject(target, selection.__fields__), ))

    def __repr__(self):
        return "SelectionSet({!r})".format(list(self.__fields__))

    # TODO: prevent `self` from conflicting with kwargs
    def __call__(self, **kwargs):
        try:
            *rest, target = self.__fields__
        except ValueError:
            raise Error('cannot call empty field list')
        return SelectionSet._make(
            tuple(rest) + (replace(target, kwargs=kwargs), ))

    def __iter__(self):
        return iter(self.__fields__)

    def __len__(self):
        return len(self.__fields__)


@dataclass
class Query(snug.Query):
    url:    str
    fields: SelectionSet

    def __gql__(self):
        return "{{\n{}\n}}".format(indent(gql(self.fields), INDENT))

    __str__ = __gql__

    def __iter__(self):
        response = yield snug.Request(
            "POST", self.url, content=json.dumps({"query": gql(self)}),
            headers={'Content-Type': 'application/json'}
        )
        return json.loads(response.content)


field_chain = SelectionSet()


class Namespace:

    def __init__(self, url: str, classes: t.Dict[str, type]):
        self._url = url
        for name, cls in classes.items():
            setattr(self, name, cls)

    def __getitem__(self, key):
        # TODO: determine query type dynamically
        return self.Query[key]
        # breakpoint()
        # return Query(self._url, key)
