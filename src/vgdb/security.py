"""Salted Argon2id password storage; report fixture strings are not valid logins."""
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

hasher = PasswordHasher()


def hash_password(password):
    if len(password) < 8:
        raise ValueError('Use a password with at least 8 characters.')
    return hasher.hash(password)


def verify_password(encoded, password):
    try:
        return hasher.verify(encoded, password)
    except (InvalidHashError, VerificationError):
        return False
