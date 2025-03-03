<script setup lang="ts">
import Papa from 'papaparse';

import IconImport from '@/components/icons/IconImport.vue';

import { useDropZone } from '@vueuse/core'
import { useFileDialog } from '@vueuse/core'
import { shallowRef, useTemplateRef, ref, defineEmits } from 'vue';

defineProps<{
  isOpen: boolean;
}>();

const emit = defineEmits(['file-uploaded']);

const filesData = shallowRef<{ name: string, size: number, type: string, lastModified: number, data: any }[]>([])
const dropZoneRef = useTemplateRef<HTMLElement>('dropZoneRef')

const { isOverDropZone } = useDropZone(dropZoneRef, { dataTypes: ['text/csv'], onDrop: onDrop })

const { files, open, reset, onCancel, onChange } = useFileDialog({
  accept: 'text/csv',
  directory: false,
})

interface FileData {
  name: string;
  size: number;
  type: string;
  lastModified: number;
  data: any;
}

function onDrop(files: File[] | null) {
  handleUpload(files);
}

onChange((files: FileList | null) => {
  const fileArray: File[] | null = files ? Array.from(files) : null;
  handleUpload(fileArray);
});

async function handleUpload(files: File[] | null) {
  if (files) {

    filesData.value = await Promise.all(
      files.map(async (file): Promise<FileData> => ({
        name: file.name,
        size: file.size,
        type: file.type,
        lastModified: file.lastModified,
        data: await readCSVFile(file),
      }))
    );

    emit('file-uploaded', filesData.value);
  } 
}

const readCSVFile = (file: File) => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const text: string = reader.result ? reader.result as string : "";
      const result = Papa.parse(text, { header: true });
      resolve(result);
    };
    reader.onerror = (error) => reject(error);
    reader.readAsText(file);
  });
};

</script>

<template>
    <div
        class="file-container"
        :style="{ opacity: isOpen ? '100%' : '0%' }"
        ref="dropZoneRef">
        <div class="file-drop-icons">
            <IconImport />
            <h3>
                <span><button class="file-button" type="button" @click="open()">Choose a file</button></span>
                <span class="file-text"> or drag it here </span>
            </h3>
        </div>
        <div class="flex flex-wrap justify-center items-center">
            <div v-for="(file, index) in filesData" :key="index" class="w-200px bg-black-200/10 ma-2 pa-6">
              <p>Name: {{ file.name }}</p>
              <p>Size: {{ file.size }}</p>
              <p>Type: {{ file.type }}</p>
              <p>Last modified: {{ file.lastModified }}</p>
            </div>
        </div>
    </div>
</template>

<style scoped>
    .file-container {
        width: 50%;
        height: 50%;
        /* opacity: 0%; */
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        background: var(--mm-beige);
        z-index: 1;

        border-radius: 10px;
        border-style: dashed;
        border-width: 1px;
    }

    .file-drop-icons {
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;

        width: 100%;

        gap: 10px;
    }

    .file-button {
    width: 120px;
    height: 25px;

    background: var(--mm-green);
    border-radius: 5px;
    border: none;

    font-family: 'Merge One';
    font-style: normal;
    font-weight: 400;
    font-size: 15px;
    line-height: 15px;
    text-align: center;

    color: #FFFFFF;
    }
</style>