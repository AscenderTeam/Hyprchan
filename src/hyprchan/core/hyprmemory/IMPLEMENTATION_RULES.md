You are a plan enforcement agent. Welcome to the HyprMemory design & implementation rule book.

Your job is to implement the memory module for the Hypr-Chan with modern RAG and Arxiv Paper approaches.
Every detail is described in `IMPLEMENTATION_PLAN.md`.

## Introduction:
Before you start planning implementation, I need you to have a clear view of what you are doing and the system your going to work with.
So you should inspect the `src/core/hypraios` for more details on with what we are planning to integrate this memory module. You aren't allowed to touch anything there though NOTE that!

The `src/core/hyprmemory` is the place where you should start planning and implementing the memory module.
The only exception is `src/entities` and `src/settings.py` where you can also work for implementing database entities 

If you need to work outside of your working space, please notify me about that and I will allow you, just don't get uncontrollable. I want you to be predictable and MAXIMUMLY efficient.
Do everything for efficiency.

## Basic rules:
1. Your workspace is mostly inside `src/core/hyprmemory` and any changes outside it - you should notify me.
2. Follow strict Single Responsibility Principle, organize utilities into utils/ directory. For layers of memories, implement different directories with each object-file responsibily.
3. Interfaces, contracts and many other abstract and type related stuff should be placed into interfaces/ directory of your working space (hyprmemory).
4. Each memory layer should be well documented, methods must contain at least a light description of what they do.
5. Please, keep code well organized, clean and readable, not all of us have 4k FULL HD and high resolution monitor to read one large lined code or large bloat of private/protected methods in one class.

## Implementation Rules:
1. The implementation plan uses certain Arxiv data and pages or at least cites them, you should include the citation or at least the link or name of the paper in methods or code implementation just to keep code well documented and readable.
2. Before implementing, be skeptic to IMPLEMENTATION_PLAN, fetch and search for Arxiv data. If you are not sure, ask me.
3. The goal is here to achieve human brain-like memory cognition and consolidation, so you should implement that with this motive and motivation.
4. Your code should be compatible with Ascender Framework's coding structure, it mostly inherits NestJS and Angular paradigm and design so NOTE that there is same DI engine as in Angular (with its own quirks).
5. For embeddings, you might need Hugging Face API or you can use OpenAI, if there is something heavy computational, please warn me about that.
6. If IMPLEMENTATION_PLAN doesn't mention, rules will notify you that in implementation there are: A-Mem, SYNAPSE, REMem, Emotional RAG and MemGPT papers are used to inspire the new memory implementation.

## Database & Code consistency rules:
1. It is highly recommended to use Redis for STM and Postgres with PGVector.
2. You should use SQLalchemy ORM for postgres and Redis from `core/redis` (inject it via DI).
3. For SQLAlchemy, ascender framework provides you `DatabaseEngine` object from `ascender.core.database`. And there are specific rules to define database entities.

## How to work with Ascender Framework's Database Engine:

There are simple steps to use it, now every database related stuff is in `ascender.core.database`.
To get started you must:
1. Configure database settings in `settings.py`, edit `DATABASE_CONNECTION` constant
2. Define entities using `DBEntity` class object from `ascender.core.database` (IT is same as `Base` object from sqlalchemy)
3. Ascender recommends using `Mapped[T]` and `mapped_column` from `sqlalchemy.orm` to define entities.
3. Name your entities with this naming conventions: `[Purpose]Entity` (e.g. NodeEntity or UserEntity)
4. Define them in `DATABASE_CONNECTION`'s "entities" field.
5. Inject the `DatabaseEngine` using `inject()` or constructor method of service marked with `@Injectable()` decorator.
5. Generate session (SQLAlchemy's AsyncSession context) by using `DatabaseEngine.generate_context()`.
6. You might be required to use PgVector extension for SQLAlchemy to get embeddings support. So note THAT too!

Code snippet examples are lower!

### Entities
```py
# src/entities/example.py

from ascender.core.database import DBEntity
from sqlalchemy.orm import Mapped, mapped_column

class ExampleEntity(DBEntity):
    __tablename__ = "examples"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column()
```

### Registering entity

```py 
# src/settings.py
...

DATABASE_CONNECTION = {
    ...,
    "entities": [
        "entities.example", # used as import, src/ is root path. It resolves ExamplEntity by importing it from `entities.example`
    ]
}
```

### Injecting database engine

```py
# src/services/example_service.py

from ascender.core.database import DatabaseEngine

@Injectable(provided_in="root")
class ExampleService:
    def __init__(self, database: DatabaseEngine):
        self._context = database.generate_context()

    async def do_something(self):
        async with self._context() as session:
            ...
```

### Ascender Framework's new & fast query API

Since it takes 3 or more lines of code to simply query database and get/fetch data, Ascender Framework introduces `Constructor[T]` object to make it in one simple line like in Django ORM.

```py 
# src/services/example_service.py

from ascender.core.database import DatabaseEngine
from entities.example import ExampleEntity

@Injectable(provided_in="root")
class ExampleService:
    def __init__(self, database: DatabaseEngine):
        self._context = database.generate_context()

    async def get_from_name(self, name: str):
        query = await self._context.construct(ExampleEntity).filter(ExampleEntity.name == name)

        return query.scalar() # Result field with scalar() and scalars() method, ascender framework auto executes it under the hood quickly and returns result like this
        
```

## Embeddings & PGVector

1. The rule doesn't enforce you to use pgvector speciifcally.
2. You can use that extension ONLY if it supported by async engine of SQLAlchemy.


## As soon as you finish the work.
1. Create markdown file in your working space I marked with name: `WALKTHROUGH.md`.
2. Describe in well mannered and well documented way on how everything was implemented, where located and how to use or continue maintaining it.
3. Let me have full and clear view on how it was implemented.
4. Use markdown and include sources of code and maybe usage examples.
5. Clarify single access API and HyrpAIOS implementation plans for it as well.

I wish you goodluck and NOTE, do not violate rules.
