from datetime import datetime
from operator import itemgetter
import re

from django.template.defaultfilters import date as _date
from no_sql_client import NoSQLClient
from cloudant.document import Document

import unicodedata
from grm.constants import ADMINISTRATIVE_LEVEL_TYPE
from collections import Counter
from datetime import datetime


def structure_the_words(word):
    return (" ").join(re.findall(r"[A-Z][^A-Z]*|[^A-Z]+", word)).lower().capitalize()


def strip_accents(s):
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def sort_dictionary_list_by_field(list_to_be_sorted, field, reverse=False):
    return sorted(list_to_be_sorted, key=itemgetter(field), reverse=reverse)


def get_month_range(start, end=datetime.now(), fmt="Y F"):
    start = start.month + 12 * start.year
    end = end.month + 12 * end.year
    months = list()
    for month in range(start - 1, end):
        y, m = divmod(month, 12)
        months.insert(0, (f"{y}-{m+1}", _date(datetime(y, m + 1, 1), fmt)))
    return months


def unix_time_millis(dt):
    epoch = datetime.utcfromtimestamp(0)
    return int((dt - epoch).total_seconds() * 1000)


def clean_not_same_leveladministrative_levels(query_result):
    level_counts = Counter(item["administrative_level"] for item in query_result)
    most_common_level = level_counts.most_common(1)[0][0]
    query_result = [
        item
        for item in query_result
        if item["administrative_level"] == most_common_level
    ]
    return query_result


def get_choices(query_result, id_key="id", text_key="name", empty_choice=True):
    # choices = list({(i[id_key], i[text_key]) for i in query_result})
    choices = []
    [choices.append((i[id_key], i[text_key])) for i in query_result if i not in choices]
    if empty_choice:
        choices = [("", "")] + choices
    return choices


def get_administrative_levels_by_level(administrative_levels_db, level=None):
    filters = {"type": "administrative_level"}
    if level:
        filters["administrative_level"] = level
    else:
        filters["parent_id"] = None
    parent_id = administrative_levels_db.get_query_result(filters)[:][0][
        "administrative_id"
    ]
    data = administrative_levels_db.get_query_result(
        {
            "type": "administrative_level",
            "parent_id": parent_id,
        }
    )
    # data = clean_not_same_leveladministrative_levels(data)
    data = [doc for doc in data]
    return data


def get_administrative_levels_by_level_and_name(
    administrative_levels_db, level, name, empty_choice=True, attrs={}
):
    filters = {
        "type": "administrative_level",
        "administrative_level": level,
        "name": name,
    }
    for attr, value in attrs.items():
        filters[attr] = value
    query_result = administrative_levels_db.get_query_result(filters)
    return query_result


def get_administrative_levels_by_type(
    administrative_levels_db, level, empty_choice=True, attrs={}
):
    filters = {"type": "administrative_level", "administrative_level": level}
    for attr, value in attrs.items():
        filters[attr] = value
    query_result = administrative_levels_db.get_query_result(filters)
    return query_result


def get_administrative_levels_by_sql_id(
    administrative_levels_db, sql_id, empty_choice=True, attrs={}
):
    filters = {"type": "administrative_level", "administrative_id": sql_id}
    for attr, value in attrs.items():
        filters[attr] = value
    query_result = administrative_levels_db.get_query_result(filters)
    return query_result


def get_all_docs_administrative_levels_by_type(administrative_levels, level):
    result = []
    for doc in administrative_levels:
        doc = doc.get("doc")
        if (
            doc.get("type") == "administrative_level"
            and doc.get("administrative_level") == level
        ):
            result.append(doc)
    return result


def get_all_docs_administrative_levels_by_type_and_parent_id(
    administrative_levels, level, parent_id
):
    result = []
    for doc in administrative_levels:
        doc = doc.get("doc")
        if (
            doc.get("type") == "administrative_level"
            and doc.get("administrative_level") == level
            and doc.get("parent_id") == parent_id
        ):
            result.append(doc)
    return result


def get_all_docs_administrative_levels_by_type_and_administrative_id(
    administrative_levels, level, administrative_id
):
    result = []
    for doc in administrative_levels:
        doc = doc.get("doc")
        if (
            doc.get("type") == "administrative_level"
            and doc.get("administrative_level") == level
            and doc.get("administrative_id") == administrative_id
        ):
            result.append(doc)
    return result


def get_all_docs_administrative_levels_by_type_and_parent_id_include_parent(
    administrative_levels, level, parent_level, parent_id
):
    result = []
    for doc in administrative_levels:
        doc = doc.get("doc")
        if (
            doc.get("type") == "administrative_level"
            and doc.get("administrative_level") == level
            and doc.get("parent_id") == parent_id
        ) or (
            doc.get("type") == "administrative_level"
            and doc.get("administrative_level") == parent_level
            and doc.get("administrative_id") == parent_id
        ):
            result.append(doc)
    return result


def get_administrative_level_choices(administrative_levels_db, empty_choice=True):
    country_id = administrative_levels_db.get_query_result(
        {
            "type": "administrative_level",
            "parent_id": None,
        }
    )[:][0]["administrative_id"]
    query_result = administrative_levels_db.get_query_result(
        {
            "type": "administrative_level",
            "parent_id": country_id,
        }
    )
    # fix to make sure administrative levels in query_result
    # are on the same level. Maybe irrelevant depending on the dataset
    query_result = clean_not_same_leveladministrative_levels(query_result)

    return get_choices(query_result, "administrative_id", "name", empty_choice)


def get_child_administrative_levels(administrative_levels_db, parent_id):
    data = administrative_levels_db.get_query_result(
        {
            "type": "administrative_level",
            "parent_id": parent_id,
        }
    )
    data = [doc for doc in data]
    return data


def get_parent_administrative_level(administrative_levels_db, administrative_id):
    parent = None
    docs = administrative_levels_db.get_query_result(
        {"administrative_id": administrative_id, "type": "administrative_level"}
    )

    try:
        doc = administrative_levels_db[docs[0][0]["_id"]]
        if "parent_id" in doc and doc["parent_id"]:
            administrative_id = doc["parent_id"]
            docs = administrative_levels_db.get_query_result(
                {"administrative_id": administrative_id, "type": "administrative_level"}
            )
            parent = administrative_levels_db[docs[0][0]["_id"]]
    except Exception:
        pass
    return parent


def get_region_of_village_by_sql_id(administrative_levels_db, village_sql_id):
    canton = get_parent_administrative_level(administrative_levels_db, village_sql_id)
    if canton:
        commune = get_parent_administrative_level(
            administrative_levels_db, canton["administrative_id"]
        )
        if commune:
            prefecture = get_parent_administrative_level(
                administrative_levels_db, commune["administrative_id"]
            )
            if prefecture:
                return get_parent_administrative_level(
                    administrative_levels_db, prefecture["administrative_id"]
                )

    return None


def get_departement_of_administrative_level_by_sql_id(administrative_levels_db, sql_id):
    departement = parent = None
    adm_lvl = get_administrative_levels_by_sql_id(administrative_levels_db, sql_id)[:][
        0
    ]
    if adm_lvl["administrative_level"] == ADMINISTRATIVE_LEVEL_TYPE.DÉPARTEMENT:
        departement = adm_lvl
    else:
        parent = get_parent_administrative_level(
            administrative_levels_db, adm_lvl["administrative_id"]
        )
        # keep fetching parent until it's a "département",
        # using range to avoid potential infinite loop
        for i in range(1, len(ADMINISTRATIVE_LEVEL_TYPE)):
            if parent["administrative_level"] == ADMINISTRATIVE_LEVEL_TYPE.DÉPARTEMENT:
                departement = parent
                break
            parent = get_parent_administrative_level(
                administrative_levels_db, parent["administrative_id"]
            )
    return departement


def get_documents_by_type(db, _type, empty_choice=True, attrs={}):
    filters = {"type": _type}
    for attr, value in attrs.items():
        filters[attr] = value
    query_result = db.get_query_result(filters)
    return query_result


def get_first_word(sentence):
    words = sentence.split()
    if words:
        return words[0]
    else:
        return None