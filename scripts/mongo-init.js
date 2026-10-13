db.getSiblingDB('admin').createUser({
  user: 'hawkerflow', pwd: 'hawkerflow_mongo_dev',
  roles: ['hawkerflow','hawkerflow_test','hawkerflow_benchmark'].flatMap(name => [
    {role:'readWrite',db:name}, {role:'dbAdmin',db:name}
  ])
});
