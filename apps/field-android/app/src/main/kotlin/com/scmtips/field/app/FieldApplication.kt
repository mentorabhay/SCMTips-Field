package com.scmtips.field.app

import android.app.Application

/** Holds the single [SliceController] for the process (field-test slice; no DI framework needed). */
class FieldApplication : Application() {
    val controller: SliceController by lazy { SliceController(this) }
}
