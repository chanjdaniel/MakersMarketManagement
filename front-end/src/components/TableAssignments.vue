import axios from 'axios';

<template>
  <div>
    <h1>Table Assignments</h1>
    <ul>
      <li v-for="table in tables" :key="table.table_number">
        {{ table.table_number }} - {{ table.assignee }}
      </li>
    </ul>
    <h2>Add a New Table</h2>
    <form @submit.prevent="addTable">
      <input type="number" v-model="newTable.table_number" placeholder="Table Number" required />
      <input type="text" v-model="newTable.assignee" placeholder="Assignee" required />
      <button type="submit">Add Table</button>
    </form>
  </div>
</template>

<script>
import axios from 'axios';

export default {
  data() {
    return {
      tables: [],
      newTable: {
        table_number: '',
        assignee: ''
      }
    };
  },
  mounted() {
    axios.get('/tables')
      .then(response => {
        this.tables = response.data;
      })
      .catch(error => {
        console.error('Error fetching tables:', error);
      });
  },
  methods: {
    addTable() {
      axios.post('/add', this.newTable)
        .then(response => {
          this.tables = response.data.data;
          this.newTable = { table_number: '', assignee: '' };
        })
        .catch(error => {
          console.error('Error adding table:', error);
        });
    }
  }
};
</script>

<style scoped>
/* Add your component-specific styles here */
</style>