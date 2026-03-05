from flask import Blueprint, jsonify, Response, request
from freshquant.db import get_db
from freshquant.util.url import fq_util_parse_query_params
from bson import json_util, ObjectId
import math

general_bp = Blueprint('general', __name__, url_prefix='/api')

@general_bp.route('/general/<db_name>/<collection_name>', methods=['GET'])
def get_all_documents(db_name, collection_name):
    db = get_db(db_name)
    collection = db[collection_name]
    query, page, size, sort, project = fq_util_parse_query_params(request.args.to_dict())
    skip = (page - 1) * size
    documents = list(collection.find(query, project).sort(sort).skip(skip).limit(size))
    total_records = collection.count_documents(query)
    total_pages = math.ceil(total_records / size)
    return Response(
        json_util.dumps(
            {
                "data": documents,
                "page": page,
                "size": size,
                "total_records": total_records,
                "total_pages": total_pages,
            }
        ),
        mimetype="application/json",
    )


@general_bp.route('/general/<db_name>/<collection_name>/<id>', methods=['GET'])
def get_document_by_id(db_name, collection_name, id):
    db = get_db(db_name)
    collection = db[collection_name]
    try:
        document = collection.find_one({'_id': ObjectId(id)})
    except:
        return jsonify({'error': 'Invalid document ID format'})
    if document:
        return Response(
            json_util.dumps({"data": document}), mimetype="application/json"
        )
    else:
        return jsonify({'error': 'Document not found'})


@general_bp.route('/general/<db_name>/<collection_name>', methods=['POST'])
def create_document(db_name, collection_name):
    db = get_db(db_name)
    collection = db[collection_name]
    payload = request.json
    is_multi = payload.pop("is_multi", False)
    data = payload.pop("data", None)
    if not data:
        return jsonify({'error': 'Documents not found'})
    if is_multi:
        result = collection.insert_many(data)
        return jsonify({'ids': [str(id) for id in result.inserted_ids]})
    else:
        data['_id'] = ObjectId(data['_id']['$oid'])
        result = collection.insert_one(data)
    return jsonify({'id': str(result.inserted_id)})


@general_bp.route('/general/<db_name>/<collection_name>/<id>', methods=['PUT'])
def update_document(db_name, collection_name, id):
    db = get_db(db_name)
    collection = db[collection_name]
    payload = request.json
    data = payload.pop("data", None)
    if not data:
        return jsonify({'error': 'Document not found'})
    # 排除_id字段，因为它已经在路径参数中传递
    if '_id' in data:
        data.pop('_id')
    try:
        result = collection.update_one({'_id': ObjectId(id)}, {"$set": data})
        if result.matched_count == 0:
            return jsonify({'error': 'Document not found'})
        elif result.modified_count == 0:
            document = collection.find_one({'_id': ObjectId(id)})
            return jsonify({'message': 'No changes made to document', '_id': str(document['_id']), 'name': document.get('name')})
        else:
            document = collection.find_one({'_id': ObjectId(id)})
            return jsonify({'message': 'Document updated', '_id': str(document['_id']), 'name': document.get('name')})
    except:
        return jsonify({'error': 'Invalid document ID format'})


@general_bp.route('/general/<db_name>/<collection_name>', methods=['PUT'])
def update_documents(db_name, collection_name):
    db = get_db(db_name)
    collection = db[collection_name]
    payload = request.json
    cond = payload.pop("cond", None)
    data = payload.pop("data", None)
    if not cond:
        return jsonify({'error': 'Condition not found'})
    if not data:
        return jsonify({'error': 'Document not found'})
    result = collection.update_many(cond, {"$set": data})
    if result.matched_count >= 1:
        return jsonify({'message': 'Document updated'})
    else:
        return jsonify({'error': 'Document not found'})


@general_bp.route('/general/<db_name>/<collection_name>/<id>', methods=['DELETE'])
def delete_document(db_name, collection_name, id):
    db = get_db(db_name)
    collection = db[collection_name]
    try:
        result = collection.delete_one({'_id': ObjectId(id)})
    except:
        return jsonify({'error': 'Invalid document ID format'})
    if result.deleted_count == 1:
        return jsonify({'message': 'Document deleted'})
    else:
        return jsonify({'error': 'Document not found'})


@general_bp.route('/general/<db_name>/<collection_name>', methods=['DELETE'])
def delete_documents(db_name, collection_name, id):
    db = get_db(db_name)
    collection = db[collection_name]
    payload = request.json
    cond = payload.pop("cond", None)
    if not cond:
        return jsonify({'error': 'Condition not found'})
    result = collection.delete_many(cond)
    if result.deleted_count >= 1:
        return jsonify({'message': 'Document deleted'})
    else:
        return jsonify({'error': 'Document not found'})