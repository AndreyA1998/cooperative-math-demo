"""Pure JSON request dispatch for native Python and a Pyodide worker.

The boundary accepts and returns serialized JSON. Keeping schemas as raw text
across JavaScript preserves integer tokens beyond the Number precision limit.
No network server, Python evaluation, or filesystem route is exposed here.
"""
from functools import lru_cache
import json
import re
from secrets import randbits
from urllib.parse import parse_qs

from template_dataset import describe, generate
from composite_dataset import build_schema, instantiate
from source_dataset.loader import load_corpus
from template_dataset.registry import UnsupportedProblemError, registry
from composite_dataset.serialization import loads_json
from .presentation import _presentation_validated, presentation, atomic_presentation, _display_value

ATOMIC_ROUTES = {
    "/api/catalogue": set(),
    "/api/describe": {"id"},
    "/api/template": {"id"},
    "/api/generate": {"id", "seed"},
}
BUILD = "/api/composite/build"
INSTANTIATE = "/api/composite/instantiate"
PRESENTATION = "/api/composite/presentation"
VARIANT = "/api/composite/variant"
COMPOSITE_FIELDS = {
    BUILD: {"depth", "width", "seed", "split", "allow_template_reuse"},
    INSTANTIATE: {"schema", "seed"},
    PRESENTATION: {"schema", "seed"},
    VARIANT: {"schema", "seed"},
}
# The schema itself has an independent 8 MiB validation limit.
MAX_BODY_BYTES = 9 * 1024 * 1024
PROBLEM_ID = re.compile(r"[a-z_]{1,32}/(?:train|test)/[0-9]{1,9}")
DECIMAL_SEED = re.compile(r"[0-9]{1,20}")
MAX_SEED = 2**64 - 1


class RequestError(ValueError):
    """An invalid request with a fixed, user-facing message."""


@lru_cache(maxsize=1)
def catalogue():
    corpus = load_corpus()
    return {
        "problems": [
            {"id": problem_id, "split": corpus[problem_id]["split"],
             "subject": corpus[problem_id]["subject"]}
            for problem_id in sorted(registry())
        ]
    }


def _seed(text):
    if not isinstance(text, str) or not DECIMAL_SEED.fullmatch(text) or int(text) > MAX_SEED:
        raise RequestError("Seed должен быть десятичной строкой от 0 до 18446744073709551615.")
    return int(text)


def atomic_response(path, query):
    try:
        fields = parse_qs(query, keep_blank_values=True, strict_parsing=True,
                          max_num_fields=2, errors="strict") if query else {}
    except ValueError as error:
        raise RequestError("Некорректные параметры запроса.") from error
    if fields.keys() - ATOMIC_ROUTES[path] or any(len(values) != 1 for values in fields.values()):
        raise RequestError("Некорректные параметры запроса.")
    if path == "/api/catalogue":
        return catalogue()

    problem_id = fields.get("id", [""])[0]
    if not PROBLEM_ID.fullmatch(problem_id):
        raise RequestError("Введите ID в формате prealgebra/test/11.")
    if path == "/api/describe":
        return describe(problem_id)
    if path == "/api/template":
        return dict(describe(problem_id), presentation=atomic_presentation(problem_id))

    seed = _seed(fields["seed"][0]) if "seed" in fields else randbits(64)
    variant = generate(problem_id, seed)
    variant["seed"] = str(seed)
    variant["parameter_display"] = {
        name: _display_value(value)
        for name, value in variant["parameters"].items()
    }
    variant["presentation"] = atomic_presentation(problem_id, variant["parameters"])
    return variant


def composite_response(path, fields):
    """Handle already decoded fields; schema entry points remain strict."""
    if not isinstance(fields, dict) or fields.keys() != COMPOSITE_FIELDS[path]:
        raise RequestError("Некорректный набор полей запроса.")
    if path != BUILD and not isinstance(fields["schema"], dict):
        raise RequestError("Схема должна быть объектом JSON.")
    if path == PRESENTATION and fields["seed"] is None:
        return presentation(fields["schema"])
    seed = _seed(fields["seed"])

    if path == BUILD:
        depth, width = fields["depth"], fields["width"]
        split, reuse = fields["split"], fields["allow_template_reuse"]
        if type(depth) is not int or depth < 1 or type(width) is not int or width < 1:
            raise RequestError("Глубина и ширина должны быть положительными целыми числами.")
        if split not in ("train", "test") or type(reuse) is not bool:
            raise RequestError("Выберите train или test и укажите, разрешены ли повторы.")
        return build_schema(depth, width, seed, split=split, allow_template_reuse=reuse)

    schema = fields["schema"]
    if path == PRESENTATION:
        return presentation(schema, seed)
    instance = instantiate(schema, seed)
    if path == VARIANT:
        # instantiate validates the schema and its native bottom parameters.
        # The display helper consumes exactly that instance without re-solving.
        return {"instance": instance, "presentation": _presentation_validated(schema, instance)}
    return instance


def _serialized(status, payload):
    return status, json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _error(status, message):
    return _serialized(status, {"error": message})


def dispatch_json(method, path, query="", body=None):
    """Return ``(status: int, raw_json: str)`` for one browser request.

    GET supports catalogue, describe, template and generate. POST supports composite
    build, instantiate, presentation and variant. The latter returns both the
    exact instance and its display annotations from one instantiation. Invalid
    input returns 400, unknown routes/methods return 404, and failures return 500.
    """
    if not all(isinstance(value, str) for value in (method, path, query)):
        return _error(400, "Некорректный адрес запроса.")
    if "?" in path or "#" in path:
        return _error(400, "Передайте параметры отдельно от пути запроса.")
    atomic = method == "GET" and path in ATOMIC_ROUTES
    composite = method == "POST" and path in COMPOSITE_FIELDS
    if not (atomic or composite):
        return _error(404, "Страница не найдена.")
    try:
        if atomic:
            if body is not None:
                raise RequestError("GET-запрос не должен содержать тело.")
            payload = atomic_response(path, query)
        else:
            if query:
                raise RequestError("Передайте параметры в теле JSON.")
            fields = loads_json(body, max_bytes=MAX_BODY_BYTES)
            payload = composite_response(path, fields)
        return _serialized(200, payload)
    except UnsupportedProblemError:
        return _error(404, "Для этой задачи пока нет шаблона.")
    except RequestError as error:
        return _error(400, str(error))
    except KeyError:
        if atomic:
            return _error(404, "Задача с таким ID не найдена.")
        return _error(500, "Не удалось обработать схему.")
    except ValueError as error:
        if composite:
            return _error(400, str(error))
        return _error(500, "Генератор не смог построить вариант.")
    except Exception:
        # This transport boundary must return a JSON error even if core code fails.
        message = "Не удалось обработать схему." if composite else "Генератор не смог построить вариант."
        return _error(500, message)
