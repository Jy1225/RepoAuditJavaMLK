class ListenerRegistry {
    public void addListener(Object listener) {}
    public void removeListener(Object listener) {}
}

class MLKCase08_ListenerLeak {
    private final ListenerRegistry bus = new ListenerRegistry();

    public void run(Object listener) {
        bus.addListener(listener);
    }
}
