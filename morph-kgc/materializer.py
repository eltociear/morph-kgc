""" Morph-KGC """

__author__ = "Julián Arenas-Guerrero"
__copyright__ = "Copyright (C) 2020 Julián Arenas-Guerrero"
__credits__ = ["Julián Arenas-Guerrero"]

__license__ = "Apache-2.0"
__version__ = "0.1"
__maintainer__ = "Julián Arenas-Guerrero"
__email__ = "arenas.guerrero.julian@outlook.com"
__status__ = 'Prototype'


import logging
import re
import pandas as pd

import relational_source

from urllib.parse import quote


ENGINE_DELIMITERS = {
    'mysql': '`',
    'postgresql': '"',
    'oracle': '"',
    'sqlserver': '"'
}


def _get_references_in_template(template):
    template = template.replace('\{', 'zwy\u200B').replace('\}', 'ywz\u200A')

    references = re.findall('\{([^}]+)', template)
    references = [reference.replace('zwy\u200B', '\{').replace('ywz\u200A', '\}') for reference in references]

    return references


def _get_references_in_mapping_rule(mapping_rule, only_subject_map=False):
    references = []
    if pd.notna(mapping_rule['subject_template']):
        references.extend(_get_references_in_template(str(mapping_rule['subject_template'])))
    elif pd.notna(mapping_rule['subject_reference']):
        references.append(str(mapping_rule['subject_reference']))

    if not only_subject_map:
        if pd.notna(mapping_rule['predicate_template']):
            references.extend(_get_references_in_template(str(mapping_rule['predicate_template'])))
        elif pd.notna(mapping_rule['predicate_reference']):
            references.append(str(mapping_rule['predicate_reference']))
        if pd.notna(mapping_rule['object_template']):
            references.extend(_get_references_in_template(str(mapping_rule['object_template'])))
        elif pd.notna(mapping_rule['object_reference']):
            references.append(str(mapping_rule['object_reference']))

    return set(references)


def _materialize_template(query_results_df, template, columns_alias='', termtype='http://www.w3.org/ns/r2rml#IRI', language_tag='', datatype=''):
    references = _get_references_in_template(str(template))

    if str(termtype).strip() == 'http://www.w3.org/ns/r2rml#Literal':
        query_results_df['triple'] = query_results_df['triple'] + '"'
    else:
        query_results_df['triple'] = query_results_df['triple'] + '<'

    for reference in references:
        query_results_df['reference_results'] = query_results_df[columns_alias + reference]

        if str(termtype).strip() == 'http://www.w3.org/ns/r2rml#IRI':
            query_results_df['reference_results'] = query_results_df['reference_results'].apply(lambda x: quote(x))

        splitted_template = template.split('{' + reference + '}')
        query_results_df['triple'] = query_results_df['triple'] + splitted_template[0]
        query_results_df['triple'] = query_results_df['triple'] + query_results_df['reference_results']
        template = str('{' + reference + '}').join(splitted_template[1:])

    if str(termtype).strip() == 'http://www.w3.org/ns/r2rml#Literal':
        query_results_df['triple'] = query_results_df['triple'] + '"'
        if language_tag:
            query_results_df['triple'] = query_results_df['triple'] + '@' + language_tag + ' '
        elif datatype:
            query_results_df['triple'] = query_results_df['triple'] + '^^<' + datatype + '> '
        else:
            query_results_df['triple'] = query_results_df['triple'] + ' '
    else:
        query_results_df['triple'] = query_results_df['triple'] + '> '

    return query_results_df


def _materialize_reference(query_results_df, reference, columns_alias='', termtype='http://www.w3.org/ns/r2rml#Literal', language_tag='', datatype=''):
    query_results_df['reference_results'] = query_results_df[columns_alias + str(reference)]

    if str(termtype).strip() == 'http://www.w3.org/ns/r2rml#IRI':
        query_results_df['reference_results'] = query_results_df['reference_results'].apply(lambda x: quote(x, safe='://'))
        query_results_df['triple'] = query_results_df['triple'] + '<' + query_results_df['reference_results'] + '> '
    elif str(termtype).strip() == 'http://www.w3.org/ns/r2rml#Literal':
        query_results_df['triple'] = query_results_df['triple'] + '"' + query_results_df['reference_results'] + '"'
        if language_tag:
            query_results_df['triple'] = query_results_df['triple'] + '@' + language_tag + ' '
        elif datatype:
            query_results_df['triple'] = query_results_df['triple'] + '^^<' + datatype + '> '
        else:
            query_results_df['triple'] = query_results_df['triple'] + ' '

    return query_results_df


def _materialize_constant(query_results_df, constant, termtype='http://www.w3.org/ns/r2rml#IRI', language_tag='', datatype=''):
    if str(termtype).strip() == 'http://www.w3.org/ns/r2rml#Literal':
        complete_constant = '"' + constant + '"'

        if language_tag:
            complete_constant = complete_constant + '@' + language_tag + ' '
        elif datatype:
            complete_constant = complete_constant + '^^<' + datatype + '> '
        else:
            complete_constant = complete_constant + ' '
    else:
        complete_constant = '<' + str(constant) + '> '

    query_results_df['triple'] = query_results_df['triple'] + complete_constant

    return query_results_df


def _materialize_mapping_rule(mapping_rule, subject_maps_df, config):
    query = 'SELECT '
    if config.getboolean('CONFIGURATION', 'push_down_distincts'):
        query = query + 'DISTINCT '

    if pd.notna(mapping_rule['object_parent_triples_map']):
        child_references = _get_references_in_mapping_rule(mapping_rule)

        parent_triples_map_rule = \
            subject_maps_df[subject_maps_df.triples_map_id==mapping_rule['object_parent_triples_map']].iloc[0]
        parent_references = _get_references_in_mapping_rule(parent_triples_map_rule, only_subject_map=True)

        for key, join_condition in eval(mapping_rule['join_conditions']).items():
            parent_references.add(join_condition['parent_value'])
            child_references.add(join_condition['child_value'])

        child_query = 'SELECT '
        if len(child_references) > 0:
            for reference in child_references:
                child_query = child_query + reference + ' AS child_' + reference + ', '
            child_query = child_query[:-2] + ' FROM ' + mapping_rule['tablename'] + ' WHERE '
            for reference in child_references:
                child_query = child_query + reference + ' IS NOT NULL AND '
            child_query = child_query[:-5]
        else:
            child_query = None

        parent_query = 'SELECT '
        if len(parent_references) > 0:
            for reference in parent_references:
                parent_query = parent_query + reference + ' AS parent_' + reference + ', '
            parent_query = parent_query[:-2] + ' FROM ' + parent_triples_map_rule['tablename'] + ' WHERE '
            for reference in parent_references:
                parent_query = parent_query + reference + ' IS NOT NULL AND '
            parent_query = parent_query[:-5]
        else:
            parent_query = None

        query = query + '* FROM (' + child_query + ') AS child, (' + parent_query + ') AS parent WHERE '
        for key, join_condition in eval(mapping_rule['join_conditions']).items():
            query = query + 'child.child_' + join_condition['child_value'] + \
                    '=parent.parent_' + join_condition['parent_value'] + ' AND '
        query = query[:-4] + ';'

        query_results_df = relational_source.execute_relational_query(query, config, mapping_rule['source_name'])

        query_results_df['triple'] = ''
        if pd.notna(mapping_rule['subject_template']):
            query_results_df = _materialize_template(
                query_results_df, mapping_rule['subject_template'], termtype=mapping_rule['subject_termtype'], columns_alias='child_')
        elif pd.notna(mapping_rule['subject_constant']):
            query_results_df = _materialize_constant(query_results_df, mapping_rule['subject_constant'], termtype=mapping_rule['subject_termtype'])
        elif pd.notna(mapping_rule['subject_reference']):
            query_results_df = _materialize_reference(
                query_results_df, mapping_rule['subject_reference'], termtype=mapping_rule['subject_termtype'], columns_alias='child_')
        if pd.notna(mapping_rule['predicate_template']):
            query_results_df = _materialize_template(
                query_results_df, mapping_rule['predicate_template'], columns_alias='child_')
        elif pd.notna(mapping_rule['predicate_constant']):
            query_results_df = _materialize_constant(query_results_df, mapping_rule['predicate_constant'])
        elif pd.notna(mapping_rule['predicate_reference']):
            query_results_df = _materialize_reference(
                query_results_df, mapping_rule['predicate_reference'], columns_alias='child_')
        if pd.notna(parent_triples_map_rule['subject_template']):
            query_results_df = _materialize_template(
                query_results_df, parent_triples_map_rule['subject_template'], termtype=parent_triples_map_rule['subject_termtype'], columns_alias='parent_')
        elif pd.notna(parent_triples_map_rule['subject_constant']):
            query_results_df = _materialize_constant(query_results_df, parent_triples_map_rule['subject_constant'], termtype=parent_triples_map_rule['subject_termtype'])
        elif pd.notna(parent_triples_map_rule['subject_reference']):
            query_results_df = _materialize_reference(
                query_results_df, parent_triples_map_rule['subject_reference'], termtype=parent_triples_map_rule['subject_termtype'], columns_alias='parent_')

    else:
        references = _get_references_in_mapping_rule(mapping_rule)

        if len(references) > 0:
            for reference in references:
                query = query + reference + ', '
            query = query[:-2] + ' FROM ' + mapping_rule['tablename'] + ' WHERE '
            for reference in references:
                query = query + reference + ' IS NOT NULL AND '
            query = query[:-4] + ';'
        else:
            query = None

        query_results_df = relational_source.execute_relational_query(query, config, mapping_rule['source_name'])

        query_results_df['triple'] = ''
        if pd.notna(mapping_rule['subject_template']):
            query_results_df = _materialize_template(query_results_df, mapping_rule['subject_template'], termtype=mapping_rule['subject_termtype'])
        elif pd.notna(mapping_rule['subject_constant']):
            query_results_df = _materialize_constant(query_results_df, mapping_rule['subject_constant'], termtype=mapping_rule['subject_termtype'])
        elif pd.notna(mapping_rule['subject_reference']):
            query_results_df = _materialize_reference(query_results_df, mapping_rule['subject_reference'], termtype=mapping_rule['subject_termtype'])
        if pd.notna(mapping_rule['predicate_template']):
            query_results_df = _materialize_template(query_results_df, mapping_rule['predicate_template'])
        elif pd.notna(mapping_rule['predicate_constant']):
            query_results_df = _materialize_constant(query_results_df, mapping_rule['predicate_constant'])
        elif pd.notna(mapping_rule['predicate_reference']):
            query_results_df = _materialize_reference(query_results_df, mapping_rule['predicate_reference'])
        if pd.notna(mapping_rule['object_template']):
            query_results_df = _materialize_template(query_results_df, mapping_rule['object_template'], termtype=mapping_rule['object_termtype'], language_tag=mapping_rule['object_language'], datatype=mapping_rule['object_datatype'])
        elif pd.notna(mapping_rule['object_constant']):
            query_results_df = _materialize_constant(query_results_df, mapping_rule['object_constant'], termtype=mapping_rule['object_termtype'], language_tag=mapping_rule['object_language'], datatype=mapping_rule['object_datatype'])
        elif pd.notna(mapping_rule['object_reference']):
            query_results_df = _materialize_reference(query_results_df, mapping_rule['object_reference'], termtype=mapping_rule['object_termtype'], language_tag=mapping_rule['object_language'], datatype=mapping_rule['object_datatype'])

    return query_results_df['triple']


def _get_subject_maps_dict_from_mappings(mappings_df):
    subject_maps_df = mappings_df[[
        'triples_map_id', 'data_source', 'ref_form', 'iterator', 'tablename', 'query', 'subject_template',
        'subject_reference', 'subject_constant', 'subject_termtype',
        'graph_constant', 'graph_reference', 'graph_template']
    ]

    subject_maps_df = subject_maps_df.drop_duplicates()

    if len(list(subject_maps_df['triples_map_id'])) > len(set(subject_maps_df['triples_map_id'])):
        raise Exception('One or more triples maps have incongruencies in subject maps.')

    return subject_maps_df


def materialize(mappings_df, config):
    subject_maps_df = _get_subject_maps_dict_from_mappings(mappings_df)
    mapping_partitions = [group for _, group in mappings_df.groupby(by='mapping_partition')]

    for mapping_partition in mapping_partitions:
        triples = set()
        for i, mapping_rule in mapping_partition.iterrows():
            result_triples = _materialize_mapping_rule(mapping_rule, subject_maps_df, config)
            triples.update(set(result_triples))


    print("Number of triples: " + str(len(triples)))

    # REMOVE NON PRINTABLE CHARACTERS THIS WAY IS VERY SLOW!
    output = ''
    f = open(config.get('CONFIGURATION', 'output_dir') + '/' + config.get('CONFIGURATION', 'output_file'), "w")
    for triple in triples:
        #f.write(''.join(c for c in triple if c.isprintable()) + '.\n')
        f.write(triple + '.\n')
    f.close()
