package com.scmtips.field.app.net

/** A field-api problem response (RFC 7807): HTTP status, the FIELD-* code and its title. */
class HttpError(val status: Int, val code: String?, val title: String?, val detail: String?, message: String) : Exception(message)
