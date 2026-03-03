import java.io.FileInputStream;
import java.io.InputStream;

class MLKCase29_SwitchAllHelperCloseSafe {
    private void closeResource(InputStream in) throws Exception {
        in.close();
    }

    public void run(String path, int mode) throws Exception {
        InputStream in = new FileInputStream(path);
        switch (mode) {
            case 0:
                closeResource(in);
                break;
            case 1:
                closeResource(in);
                break;
            default:
                closeResource(in);
                break;
        }
    }
}
