import { defineStore } from 'pinia'
import type { FileOut } from '@/api/types'

export const useFileStore = defineStore('file', {
  state: () => ({
    files: [] as FileOut[],
  }),
  actions: {
    setFiles(files: FileOut[]) {
      this.files = files
    },
  },
})
