class MLKCase04_ThreadLocalLeak {
    private final ThreadLocal<String> ctx = new ThreadLocal<>();

    public void run(String id) {
        ctx.set(id);
    }
}
