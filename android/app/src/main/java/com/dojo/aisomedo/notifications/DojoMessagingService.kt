package com.dojo.aisomedo.notifications

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class DojoMessagingService : FirebaseMessagingService() {
    override fun onNewToken(token: String) { PushRuntime.get(this).refresh(token) }
    override fun onMessageReceived(message: RemoteMessage) {
        PushRuntime.get(this).receive(message.data + mapOf("title" to (message.notification?.title ?: message.data["title"].orEmpty()),
            "body" to (message.notification?.body ?: message.data["body"].orEmpty())))
    }
}
