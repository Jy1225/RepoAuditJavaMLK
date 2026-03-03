class ListenerRegistrySafe {
    public void addListener(Object listener) {}
    public void removeListener(Object listener) {}
}

class MLKCase09_ListenerSafe {
    private final ListenerRegistrySafe bus = new ListenerRegistrySafe();

    public void run(Object listener) {
        bus.addListener(listener);
        bus.removeListener(listener);
    }
}
