# DronePad UML – Mermaid versions (for markdown or docs)

## Class Diagram (Data Model)
```mermaid
classDiagram
  class Pad {
    +int id
    +str name
    +str zone
    +str payload_classes
    +int turnaround_minutes
    +int separation_seconds
    +bool out_of_service
  }
  class Reservation {
    +UUID id
    +int pad_id
    +str payload_class
    +datetime start_ts
    +datetime end_ts
    +enum status
    +datetime created_at
    +datetime checkin_ts
  }
  Pad "1" o-- "0..*" Reservation : reserves >
```

## Sequence – Search & Reserve
```mermaid
sequenceDiagram
  actor User
  participant App as Flask app (app.py)
  participant DB as SQLite (dronepad.db)

  User->>App: POST /search(zone,payload,start,end,turnaround)
  App->>App: parse_dt + validate
  App->>DB: SELECT pads (zone, oos=0)
  loop per pad
    App->>DB: SELECT reservations in window +/-60m
    App->>App: overlaps_with_separation()
  end
  App-->>User: render results.html (slots)

  User->>App: POST /reserve(pad_id,start,end,payload)
  App->>DB: SELECT pad
  App->>DB: SELECT reservations +/-60m
  App->>App: overlaps_with_separation()
  App->>DB: INSERT reservation
  App-->>User: redirect /reservation/{id}
```

## Sequence – Check-in & Release
```mermaid
sequenceDiagram
  actor User
  participant App as Flask app
  participant DB as SQLite

  User->>App: POST /reservation/{id}/checkin
  App->>DB: SELECT reservation
  App->>App: time window check [start-2m, end]
  App->>DB: UPDATE status=CHECKED_IN, checkin_ts
  App-->>User: redirect reservation page

  User->>App: POST /reservation/{id}/release
  App->>DB: SELECT reservation
  App->>App: if now >= start+2m and CONFIRMED
  App->>DB: UPDATE status=RELEASED
  App-->>User: redirect home
```

## Sequence – Admin toggle OOS
```mermaid
sequenceDiagram
  actor Operator
  participant App as Flask app
  participant DB as SQLite
  Operator->>App: GET /admin
  App->>DB: SELECT pads, upcoming
  App-->>Operator: render admin
  Operator->>App: POST /admin toggle_oos
  App->>DB: SELECT out_of_service
  App->>DB: UPDATE out_of_service
  App-->>Operator: flash + admin
```

## Deployment
```mermaid
flowchart LR
  Browser["User Browser"] -->|HTTP| Flask["Flask (app.py)"]
  Flask -->|sqlite3| DB["SQLite: dronepad.db"]
```