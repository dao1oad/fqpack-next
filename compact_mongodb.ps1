docker exec -it fq_mongodb mongosh quantaxis --eval "db.getCollectionNames().forEach(function(c) { 
    if(!c.startsWith('system.')) {
        print('正在整理集合: ' + c); 
        db.runCommand({compact: c}); 
    }
}); print('所有集合整理完毕！');"

docker exec -it fq_mongodb mongosh freshquant --eval "db.getCollectionNames().forEach(function(c) { 
    if(!c.startsWith('system.')) {
        print('正在整理集合: ' + c); 
        db.runCommand({compact: c}); 
    }
}); print('所有集合整理完毕！');"