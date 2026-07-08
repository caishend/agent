import { defineStore } from 'pinia'
import { getTasks, createTask, deleteTask } from '../api/task'

export const useTaskStore = defineStore('task', {
  state: () => ({
    tasks: [],
    currentTask: null
  }),
  actions: {
    async fetchTasks() {
      this.tasks = await getTasks()
    },
    async addTask(data) {
      const task = await createTask(data)
      this.tasks.unshift(task)
      return task
    },
    async removeTask(id) {
      await deleteTask(id)
      this.tasks = this.tasks.filter(t => t.task_id !== id)
    }
  }
})
