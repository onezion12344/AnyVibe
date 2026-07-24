package com.vibe.voip

import android.os.Bundle
import android.telecom.ConnectionRequest
import android.telecom.ConnectionService
import android.telecom.PhoneAccountHandle
import android.util.Log

/**
 * System-managed ConnectionService.
 * The telecom framework binds to this service and calls onCreateIncomingConnection()
 * (or onCreateOutgoingConnection()) when a call is triggered via
 * TelecomManager.addNewIncomingCall() / placeCall().
 */
class MyConnectionService : ConnectionService() {

    companion object {
        private const val TAG = "MyConnectionService"
    }

    override fun onCreateIncomingConnection(
        phoneAccount: PhoneAccountHandle,
        request: ConnectionRequest
    ): Connection {
        Log.d(TAG, "onCreateIncomingConnection: ${request.address}")

        return VoIPConnection().apply {
            setAddress(request.address, TelecomManager.PRESENTATION_ALLOWED)
            setRinging()  // incoming — user must answer before audio starts
            putExtras(request.extras)
        }
    }

    override fun onCreateOutgoingConnection(
        phoneAccount: PhoneAccountHandle,
        request: ConnectionRequest
    ): Connection {
        Log.d(TAG, "onCreateOutgoingConnection: ${request.address}")

        return VoIPConnection().apply {
            setAddress(request.address, TelecomManager.PRESENTATION_ALLOWED)
            setDialing()
            putExtras(request.extras)
        }
    }

    override fun onConnectionAborted(connection: Connection) {
        super.onConnectionAborted(connection)
        Log.d(TAG, "onConnectionAborted")
    }
}
