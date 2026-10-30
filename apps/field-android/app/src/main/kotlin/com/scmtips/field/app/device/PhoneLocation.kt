package com.scmtips.field.app.device

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import android.os.Looper

/**
 * Location for the tower check-in, from the platform's [LocationManager] (GPS and network providers; no
 * Play Services dependency). Every fix goes to [onFix]; the check-in step keeps the latest one and the
 * server applies the geofence (accuracy must be 50 m or better).
 */
class PhoneLocation(context: Context, private val onFix: (lat: Double, lon: Double, accuracyM: Double, atMs: Long) -> Unit) {
    private val app = context.applicationContext
    private val manager = app.getSystemService(Context.LOCATION_SERVICE) as LocationManager
    private var running = false

    // All four callbacks are implemented: on Android 10 they have no default bodies.
    private val listener = object : LocationListener {
        override fun onLocationChanged(location: Location) = deliver(location)
        @Deprecated("Deprecated in Java")
        override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) = Unit
        override fun onProviderEnabled(provider: String) = Unit
        override fun onProviderDisabled(provider: String) = Unit
    }

    val permitted: Boolean
        get() = app.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED

    /** Returns false when the location permission is missing (the caller asks for it, then calls again). */
    fun start(): Boolean {
        if (running) return true
        if (app.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) return false
        running = true
        for (p in listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)) {
            if (!manager.isProviderEnabled(p)) continue
            manager.getLastKnownLocation(p)?.takeIf { System.currentTimeMillis() - it.time < 120_000 }?.let(::deliver)
            manager.requestLocationUpdates(p, 2_000L, 0f, listener, Looper.getMainLooper())
        }
        return true
    }

    fun stop() {
        if (!running) return
        running = false
        manager.removeUpdates(listener)
    }

    private fun deliver(l: Location) {
        onFix(l.latitude, l.longitude, if (l.hasAccuracy()) l.accuracy.toDouble() else 9_999.0, l.time)
    }
}
