package com.dojo.aisomedo.uploads

import android.database.Cursor
import android.database.MatrixCursor
import android.os.CancellationSignal
import android.os.ParcelFileDescriptor
import android.provider.DocumentsContract.Document
import android.provider.DocumentsContract.Root
import android.provider.DocumentsProvider
import java.io.File

/** Synthetic documents only. Never points at user media. */
class UploadTestDocumentsProvider : DocumentsProvider() {
    override fun onCreate() = true
    override fun queryRoots(projection: Array<out String>?): Cursor = MatrixCursor(projection ?: arrayOf(Root.COLUMN_ROOT_ID, Root.COLUMN_DOCUMENT_ID, Root.COLUMN_TITLE, Root.COLUMN_FLAGS)).apply {
        val values: Map<String, Any?> = mapOf(Root.COLUMN_ROOT_ID to "uploads", Root.COLUMN_DOCUMENT_ID to "root", Root.COLUMN_TITLE to "Upload test", Root.COLUMN_FLAGS to Root.FLAG_SUPPORTS_IS_CHILD)
        addRow(columnNames.map { values[it] }.toTypedArray())
    }
    override fun queryDocument(documentId: String, projection: Array<out String>?): Cursor = MatrixCursor(projection ?: arrayOf(Document.COLUMN_DOCUMENT_ID, Document.COLUMN_DISPLAY_NAME, Document.COLUMN_MIME_TYPE, Document.COLUMN_SIZE, Document.COLUMN_FLAGS)).apply {
        val file = file(documentId)
        val values: Map<String, Any?> = mapOf(Document.COLUMN_DOCUMENT_ID to documentId, Document.COLUMN_DISPLAY_NAME to "$documentId.jpg", Document.COLUMN_MIME_TYPE to "image/jpeg", Document.COLUMN_SIZE to if (documentId.startsWith("unknown")) null else file.length(), Document.COLUMN_FLAGS to 0)
        addRow(columnNames.map { values[it] }.toTypedArray())
    }
    override fun queryChildDocuments(parentDocumentId: String, projection: Array<out String>?, sortOrder: String?): Cursor = MatrixCursor(projection ?: arrayOf(Document.COLUMN_DOCUMENT_ID))
    override fun openDocument(documentId: String, mode: String, signal: CancellationSignal?): ParcelFileDescriptor {
        require(mode == "r")
        return ParcelFileDescriptor.open(file(documentId), ParcelFileDescriptor.MODE_READ_ONLY)
    }
    private fun file(id: String): File {
        require(id.matches(Regex("[a-zA-Z0-9_-]+")))
        return File(context!!.cacheDir, "upload-test-$id")
    }
}
