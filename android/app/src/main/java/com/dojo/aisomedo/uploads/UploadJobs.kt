package com.dojo.aisomedo.uploads

import android.app.job.JobParameters
import android.app.job.JobService
import android.content.Context
import android.content.pm.ServiceInfo
import android.os.Build
import androidx.annotation.RequiresApi
import androidx.work.*
import kotlinx.coroutines.*

@RequiresApi(34)
@android.annotation.SuppressLint("SpecifyJobSchedulerIdRange") // UIDT namespace is separate from WorkManager.
class UploadJobService : JobService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var running: Job? = null
    private var parameters: JobParameters? = null
    override fun onStartJob(params: JobParameters): Boolean {
        val runtime = UploadRuntime.get(this)
        val binding = params.extras.getString("binding") ?: return false
        if (!runtime.matches(binding)) return false
        val notifications = UploadNotifications(this)
        try { setNotification(params, 3301, notifications.build(runtime.rows.value.firstOrNull { eligible(it) }), JOB_END_NOTIFICATION_POLICY_REMOVE) }
        catch (_: Exception) { runtime.schedulingFailed(binding, UploadIssue.SCHEDULING); return false }
        parameters = params
        running = scope.launch {
            try {
                val result = withContext(Dispatchers.IO) { runtime.runQueue(notifications::update) }
                if (parameters === params) { parameters = null; jobFinished(params, result == QueueOutcome.RETRY) }
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) {
                runtime.schedulingFailed(binding, UploadIssue.SCHEDULING)
                if (parameters === params) { parameters = null; jobFinished(params, false) }
            }
        }
        return true
    }
    override fun onStopJob(params: JobParameters): Boolean {
        if (parameters === params) { parameters = null; running?.cancel() }
        return params.stopReason != JobParameters.STOP_REASON_USER && UploadRuntime.get(this).pending(params.extras.getString("binding") ?: "")
    }
    override fun onDestroy() { scope.cancel(); super.onDestroy() }
}

class UploadWorker(context: Context, parameters: WorkerParameters) : CoroutineWorker(context, parameters) {
    override suspend fun doWork(): Result {
        val runtime = UploadRuntime.get(applicationContext)
        val binding = inputData.getString("binding") ?: return Result.failure()
        if (Build.VERSION.SDK_INT >= 34 || !runtime.matches(binding)) return Result.success()
        val notifications = UploadNotifications(applicationContext)
        try {
            setForeground(ForegroundInfo(3301, notifications.build(runtime.rows.value.firstOrNull { eligible(it) }), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC))
            return if (runtime.runQueue(notifications::update) == QueueOutcome.RETRY) Result.retry() else Result.success()
        } catch (e: CancellationException) { throw e }
        catch (_: Exception) { runtime.schedulingFailed(binding, UploadIssue.SCHEDULING); return Result.failure() }
    }
}
