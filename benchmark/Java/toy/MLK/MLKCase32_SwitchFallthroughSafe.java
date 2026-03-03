import java.io.FileInputStream;
import java.io.InputStream;

class MLKCase32_SwitchFallthroughSafe {
    public void run(String path, int mode) throws Exception {
        InputStream in = new FileInputStream(path);
        switch (mode) {
            case 0:
            case 1:
                in.close();
                break;
            default:
                in.close();
                break;
        }
    }
}
