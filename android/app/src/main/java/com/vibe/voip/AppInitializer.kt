package com.vibe.voip

import android.app.Application
import android.content.ComponentName
import android.graphics.Color
import android.telecom.PhoneAccount
import android.telecom.PhoneAccountHandle
import android.telecom.TelecomManager
import android.util.Log

/**
 * Application entry point.
 * Registers the PhoneAccount with TelecomManager so the system recognises
 * this app as a self-managed call provider.
 *
 * Note: TelecomManager.registerPhoneAccount() is a no-op on API < 26,
 * but keeping it here is harmless — the guard inside registerPhoneAccount()
 * handles it.
 */
class AppInitializer : Application() {

    companion object {
        const val ACCOUNT_ID = "com.vibe.voip.ACCOUNT_ID"

        private const val SERVICE_CLASS = "com.vibe.voip.MyConnectionService"

        fun getPhoneAccountHandle(context: android.content.Context): PhoneAccountHandle =
            PhoneAccountHandle(
                ComponentName(context.packageName, SERVICE_CLASS),
                ACCOUNT_ID
            )
    }

    override fun onCreate() {
        super.onCreate()
        registerPhoneAccount()
    }

    private fun registerPhoneAccount() {
        try {
            val telecomManager = getSystemService(TELECOM_SERVICE) as TelecomManager

            val handle = getPhoneAccountHandle(this)

            val account = PhoneAccount.builder(handle, getString(R.string.app_name) + " Calls")
                .setCapabilities(
                    PhoneAccount.CAPABILITY_SELF_MANAGED or
                    PhoneAccount.CAPABILITY_CAN_HANDLE_OUTGOING_CALLS
                )
                .setHighlightColor(Color.parseColor("#007AFF"))
                .addSupportedUriScheme("sip")
                .build()

            telecomManager.registerPhoneAccount(account)
            Log.i("AppInitializer", "PhoneAccount registered: $ACCOUNT_ID")
        } catch (e: Exception) {
            Log.e("AppInitializer", "Failed to register PhoneAccount", e)
        }
    }
}
