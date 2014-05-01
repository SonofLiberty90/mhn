import hashlib
from datetime import datetime

from flask import Blueprint, request, jsonify
from flask.ext.mail import Message
from sqlalchemy.exc import IntegrityError
from flask_security.utils import (
        login_user as login, verify_and_update_password,
        encrypt_password, logout_user as logout)

from mhn import db, mail
from mhn import user_datastore
from mhn.common.utils import error_response
from mhn.auth.models import User, PasswdReset
from mhn.auth import errors
from mhn.auth import (
    get_datastore, login_required, roles_accepted, current_user)
from mhn.api import errors as apierrors


auth = Blueprint('auth', __name__, url_prefix='/auth')


@auth.route('/login/', methods=['POST'])
def login_user():
    if 'email' not in request.json:
        return error_response(errors.AUTH_EMAIL_MISSING, 400)
    if 'password' not in request.json:
        return error_response(errors.AUTH_PSSWD_MISSING, 400)
    # email and password are in the posted data.
    user = User.query.filter_by(
            email=request.json.get('email')).first()
    psswd_check = False
    if user:
        psswd_check = verify_and_update_password(
                request.json.get('password'), user)
    if user and psswd_check:
        login(user, remember=True)
        return jsonify(user.to_dict())
    else:
        return error_response(errors.AUTH_INCORRECT_CREDENTIALS, 401)


@auth.route('/logout/', methods=['GET'])
def logout_user():
    logout()
    return jsonify({})


@auth.route('/user/', methods=['POST'])
@auth.route('/register/', methods=['POST'])
@roles_accepted('admin')
def create_user():
    missing = User.check_required(request.json)
    if missing:
        return error_response(
                apierrors.API_FIELDS_MISSING.format(missing), 400)
    else:
        user = get_datastore().create_user(
                email=request.json.get('email'),
                password=encrypt_password(request.json.get('password')))
        userrole = user_datastore.find_role('user')
        user_datastore.add_role_to_user(user, userrole)
        try:
            db.session.add(user)
            db.session.commit()
        except IntegrityError:
            return error_response(errors.AUTH_USERNAME_EXISTS, 400)
        else:
            return jsonify(user.to_dict())


@auth.route('/user/<user_id>/', methods=['DELETE'])
@roles_accepted('admin')
def delete_user(user_id):
    user = User.query.get(user_id)
    if not user:
        return error_response(errors.AUTH_NOT_FOUND.format(user_id), 404)
    user.active= False
    db.session.add(user)
    db.session.commit()
    return jsonify({})


@auth.route('/resetrequest/', methods=['POST'])
def reset_passwd_request():
    if 'email' not in request.json:
        return error_response(errors.AUTH_EMAIL_MISSING, 400)
    email = request.json['email']
    user = User.query.filter_by(email=email).first()
    if not user:
        return error_response(errors.AUTH_NOT_FOUND.format(email), 404)
    hashstr = hashlib.sha1(str(datetime.utcnow()) + user.email).hexdigest()
    # Deactivate all other password resets for this user.
    PasswdReset.query.filter_by(user=user).update({'active': False})
    reset = PasswdReset(hashstr=hashstr, active=True, user=user)
    db.session.add(reset)
    db.session.commit()
    # Send password reset email to user.
    from mhn import mhn
    msg = Message(
            html=reset.email_body, subject='MHN Password reset',
            recipients=[user.email], sender=mhn.config['DEFAULT_MAIL_SENDER'])
    try:
        mail.send(msg)
    except:
        return error_response(errors.AUTH_SMTP_ERROR, 500)
    else:
        return jsonify({})


@auth.route('/resetpass/<user_id>/', methods=['GET', 'POST'])
@roles_accepted('admin')
def reset_passwd(user_id):
    user = User.query.get(user_id)
    if not user:
        return error_response(errors.AUTH_NOT_FOUND.format(user_id), 404)
    hashstr = hashlib.sha1(str(datetime.utcnow()) + user.email).hexdigest()
    # Deactivate all other password resets for this user.
    PasswdReset.query.filter_by(user=user).update({'active': False})
    reset = PasswdReset(hashstr=hashstr, active=True, user=user)
    db.session.add(reset)
    db.session.commit()
    # Send password reset email to user.
    from mhn import mhn
    msg = Message(
            html=reset.email_body, subject='MHN Password reset',
            recipients=[user.email], sender=mhn.config['DEFAULT_MAIL_SENDER'])
    try:
        mail.send(msg)
    except:
        return error_response(errors.AUTH_SMTP_ERROR, 500)
    else:
        return jsonify({})


@auth.route('/changepass/', methods=['POST'])
def change_passwd():
    email = request.json.get('email')
    password = request.json.get('password')
    password_repeat = request.json.get('password_repeat')
    hashstr = request.json.get('hashstr')
    if not email or not password or not password_repeat or not hashstr:
        return error_response(errors.AUTH_RESET_MISSING, 400)
    if password != password_repeat:
        return error_response(errors.AUTH_PASSWD_MATCH, 400)
    reset = db.session.query(PasswdReset).join(User).\
                filter(User.email == email, PasswdReset.active == True).\
                filter(PasswdReset.hashstr == hashstr).\
                first()
    if not reset:
        return error_response(errors.AUTH_RESET_HASH, 404)
    user = reset.user
    user.password = encrypt_password(password)
    reset.active = False
    db.session.add(user)
    db.session.add(reset)
    db.session.commit()
    return jsonify({})


@auth.route('/me/', methods=['GET'])
@login_required
def get_user():
    return jsonify(current_user.to_dict())
