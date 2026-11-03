from PySide6.QtWidgets import QListWidget
from ..Jobs import Job, JobState, RenderOptions
from ..Output import Reservations


class RenderQueue:
    def __init__(self, qlistwidget: QListWidget):
        self.queue = []
        self.qlistwidget = qlistwidget
        self.reservations = Reservations()

    def create_job(self, options):
        options.validate()
        job = Job(options)
        job.output = self.reservations.reserve(job.id, options.inputFile, options.outputPath)
        return job

    def add(self, options):
        self.queue.append(self.create_job(options))
        self.refresh()

    def refresh(self):
        self.qlistwidget.clear()
        for job in self.queue:
            text = f"{job.options.inputFile} — {job.state.value}"
            if job.error:
                text += f" — {job.error}"
            self.qlistwidget.addItem(text)

    def getQueue(self):
        return [job.options for job in self.queue if job.state == JobState.WAITING]

    def clear(self):
        for job in self.queue:
            if job.state == JobState.WAITING:
                self.reservations.release(job.id)
        self.queue = [j for j in self.queue if j.state not in (JobState.WAITING, JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED)]
        self.refresh()

    def remove(self):
        index = self.qlistwidget.currentRow()
        if 0 <= index < len(self.queue):
            job = self.queue[index]
            if job.state in (JobState.WAITING, JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED):
                self.reservations.release(job.id)
                del self.queue[index]
                self.refresh()

    def moveitem(self, direction="up"):
        index = self.qlistwidget.currentRow()
        target = index + (1 if direction == "down" else -1)
        if 0 <= index < len(self.queue) and 0 <= target < len(self.queue):
            if self.queue[index].state == self.queue[target].state == JobState.WAITING:
                self.queue[index], self.queue[target] = self.queue[target], self.queue[index]
                self.refresh()
                self.qlistwidget.setCurrentRow(target)
